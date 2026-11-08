"""The policy engine: a tier for every request, from rules alone (Phase 2, milestone 1).

How a tier is chosen (the spec, with D-029). Each step can only raise what the last one gave,
except that a matching rule replaces the default:

1. A default per tool: reads and edits inside the project are tier 1; reads and edits outside it,
   unknown tools, and Bash commands no rule matches are tier 2 (P-02).
2. Rules: the spec's example rules, built in, then yours (`~/.earshot/policy.yaml`), which replace
   a built-in rule with the same id. A trusted repo policy counts as yours. If several rules
   match, the highest tier wins.
3. An untrusted repo policy can only raise (P-11).
4. Minimums no file can lower: reads and edits outside the project, and edits to build and test
   config, are at least tier 2 (P-01, P-02). So is Bash with shell syntax, until milestone 2
   splits commands properly.
5. The never-by-voice floor is tier 3: secrets, edits to Earshot's or the agent's own files,
   force pushes, pushes to the default branch, recursive deletes, piping into a shell, and
   deploys. Until milestone 2's resolvers, the shell effects are found by pattern.

Tier 0 means tier 1 (P-02): nothing is approved without an answer. A policy file that can't be
read makes everything tier 3, so a broken file never loosens anything.
"""

from __future__ import annotations

import json
import posixpath
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any, NamedTuple

from earshot import contracts, paths
from earshot.narrator import redact
from earshot.policy.file import (
    Match,
    PolicyError,
    PolicyFile,
    Rule,
    find_repo_policy,
    load,
    trusted,
)

READ_TOOLS = {"Read", "NotebookRead", "Glob", "Grep", "LS"}
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
FOLDER_TOOLS = {"Glob", "Grep", "LS"}  # with no path, they look in the session's folder
PATH_KEYS = ("file_path", "notebook_path", "path")

PROTECTED_DIRS = (".git", ".claude", ".earshot", ".github/workflows")  # edits: tier 3 (P-01)
PROTECTED_FILES = {".envrc"}
CONFIG_FILES = {"conftest.py", "package.json", "Makefile", "pyproject.toml", "setup.py"}
SHELL_SPECIALS = set(";&|<>`$()\n\r\\{}*?![]~'\"#")  # the stub's set, until milestone 2

_START = r"(?:^|[\s/'\"=:`(])"
_END = r"(?=$|[\s'\"`;|&)<>])"
SECRET_PATHS = re.compile(  # the spec's rule, widened by P-02
    rf"{_START}\.env|id_(?:rsa|dsa|ecdsa|ed25519)|\.(?:pem|key){_END}|credentials|"
    rf"{_START}\.(?:netrc|npmrc|pypirc){_END}|\.kube/config|\.docker/config\.json"
)
FORCE_PUSH = re.compile(
    r"\bgit\b[^;&|]*\bpush\b[^;&|]*\s(?:-[a-z]*f[a-z]*|--force\S*|\+\S+)(?=\s|$)"
)
DEFAULT_BRANCH_PUSH = re.compile(r"\bgit\b[^;&|]*\bpush\b[^;&|]*[\s:](?:main|master)(?=\s|$)")
RECURSIVE_DELETE = re.compile(r"\brm\b[^;&|]*\s(?:-[a-zA-Z]*[rR][a-zA-Z]*|--recursive)(?=\s|$)")
PIPE_TO_SHELL = re.compile(
    r"\|\s*(?:sudo\s+)?(?:sh|bash|zsh|dash|ksh|fish|python3?|perl|ruby|node)\b"
)
DEPLOY = re.compile(
    r"\b(?:terraform\s+apply|kubectl\s+(?:apply|delete|rollout)|helm\s+(?:install|upgrade)|"
    r"fly\s+deploy|vercel\b[^;&|]*--prod|npm\s+publish|twine\s+upload|gh\s+release\s+create|"
    r"cdk\s+deploy|serverless\s+deploy|sls\s+deploy)\b"
)
AGENT_FILES = re.compile(r"(?:^|[\s/'\"])\.(?:claude|earshot)(?:/|$|\s)")

FLOOR = (  # the spec's never-by-voice list
    "push_to_default_branch",
    "force_push",
    "secrets",
    "delete_recursive",
    "deploy",
    "pipe_to_shell",
    "change_agent_permissions",
)

BUILT_IN = PolicyFile(  # the spec's example policy; `tests` matches the stub's test commands
    version=1,
    rules=(
        Rule(
            id="tests",
            match=Match(tool="Bash", command=r"^(?:pytest|uv run pytest|npm test)(?:\s|$)"),
            tier=1,
        ),
        Rule(
            id="install",
            match=Match(
                tool="Bash", command=r"^(?:pip|uv pip|uv add|npm|pnpm|yarn|brew) (?:install|add)\b"
            ),
            tier=2,
            critical=("package_names", "versions", "index_url"),
        ),
        Rule(
            id="push",
            match=Match(tool="Bash", command=r"^git push\b"),
            tier=2,
            resolve="git_push",
            critical=("remote", "branch", "force"),
        ),
    ),
    never_by_voice=FLOOR,
)


VOICE_TIERS = frozenset({1})  # tier 2 joins once challenge words and the voiceprint are in


class Judgement(NamedTuple):
    tier: int
    rules: tuple[str, ...]  # what decided the tier, in order
    critical: tuple[str, ...]  # the fields the narrator must speak


class Policies(NamedTuple):
    yours: PolicyFile | None = None
    repo: PolicyFile | None = None
    repo_trusted: bool = False
    errors: tuple[str, ...] = ()


def policies_for(where: paths.Paths, cwd: str) -> Policies:
    """Your policy and the repo's, as they are on disk now."""
    errors: list[str] = []
    try:
        yours = load(where.policy)
    except PolicyError as exc:
        yours, errors = None, [*errors, str(exc)]
    repo, repo_trusted = None, False
    found = find_repo_policy(cwd)
    if found is not None:
        try:
            repo = load(found)
            repo_trusted = trusted(found, where.trusted_policies)
        except PolicyError as exc:
            errors.append(str(exc))
    for policy in (yours, repo):
        unknown = set(policy.never_by_voice) - set(FLOOR) if policy else set()
        if unknown:
            errors.append(f"unknown never_by_voice effects: {', '.join(sorted(unknown))}")
    return Policies(yours, repo, repo_trusted, tuple(errors))


def judge_built_in(request: contracts.ApprovalRequest) -> Judgement:
    """A tier from the built-in rules alone, with no policy files."""
    return judge(request.tool_name, request.tool_input, request.cwd)


def judge_request(where: paths.Paths, request: contracts.ApprovalRequest) -> Judgement:
    return judge_at(where, request.tool_name, request.tool_input, request.cwd)


def judge_at(where: paths.Paths, tool_name: str, tool_input: dict[str, Any], cwd: str) -> Judgement:
    """A tier with the policy files as they are on disk now."""
    return judge(tool_name, tool_input, cwd, policies_for(where, cwd))


def judge(
    tool_name: str, tool_input: dict[str, Any], cwd: str, policies: Policies | None = None
) -> Judgement:
    policies = policies or Policies()
    if policies.errors:
        return Judgement(3, tuple(f"policy: {error}" for error in policies.errors), ())
    command = tool_input.get("command") if tool_name == "Bash" else None
    if command is not None and not isinstance(command, str):
        command = json.dumps(command)
    named = _paths(tool_name, tool_input, cwd)
    unknown_tool = policies.yours.defaults.unknown_tool if policies.yours else 2
    tier, why = _default(tool_name, named, command, unknown_tool)
    rules = [f"default: {why}"]
    critical: list[str] = []

    matched = [r for r in _your_rules(policies) if _matches(r.match, tool_name, command, named)]
    if matched:
        tier = max(r.tier for r in matched)
        rules += [f"rule {r.id}" for r in matched]
        critical += [field for r in matched for field in r.critical]
    if policies.repo is not None and not policies.repo_trusted:
        for rule in policies.repo.rules:
            if rule.tier > tier and _matches(rule.match, tool_name, command, named):
                tier = rule.tier
                rules.append(f"repo rule {rule.id} (raises only, untrusted)")

    limits = [
        (m, why) for m, why in _limits(tool_name, tool_input, named, command, cwd) if m > tier
    ]
    rules += [why for _, why in limits]  # each of these alone would raise the tier
    tier = max([tier, *(m for m, _ in limits)])
    return Judgement(max(tier, 1), tuple(rules), tuple(dict.fromkeys(critical)))


def _paths(tool_name: str, tool_input: dict[str, Any], cwd: str) -> list[str]:
    """Every path the request names, made absolute against the session's folder."""
    found = [v for k in PATH_KEYS if isinstance(v := tool_input.get(k), str) and v]
    if not found and tool_name in FOLDER_TOOLS:
        found = [cwd]
    expanded = [str(Path(p).expanduser()) if p.startswith("~") else p for p in found]
    return [posixpath.normpath(posixpath.join(cwd, p)) for p in expanded]


def _inside(path: str, cwd: str, folder_too: bool) -> bool:
    """Whether `path` is inside the session's folder; the folder itself counts only for reads."""
    root = posixpath.normpath(cwd)
    return path.startswith(root.rstrip("/") + "/") or (folder_too and path == root)


def _default(
    tool_name: str, named: list[str], command: str | None, unknown_tool: int
) -> tuple[int, str]:
    if tool_name in READ_TOOLS:
        return (1, "a read") if named else (2, "a read without a path")
    if tool_name in EDIT_TOOLS:
        return (1, "an edit") if named else (2, "an edit without a file path")
    if tool_name == "Bash":
        return (2, "a command no rule matches") if command else (2, "a command that's missing")
    return unknown_tool, f"unknown tool {tool_name}"


def _your_rules(policies: Policies) -> Iterable[Rule]:
    """The built-in rules, then yours (replacing any with the same id), then a trusted repo's."""
    mine = list(policies.yours.rules) if policies.yours else []
    if policies.repo is not None and policies.repo_trusted:
        mine += policies.repo.rules
    replaced = {rule.id for rule in mine}
    return [*(r for r in BUILT_IN.rules if r.id not in replaced), *mine]


def _matches(match: Match, tool_name: str, command: str | None, named: list[str]) -> bool:
    if match.tool is None and match.command is None and match.any_path is None:
        return False  # an empty match matches nothing
    if match.tool is not None and match.tool != tool_name:
        return False
    if match.command is not None and (command is None or not re.search(match.command, command)):
        return False
    texts = [*named, *([command] if command else [])]
    return match.any_path is None or any(re.search(match.any_path, text) for text in texts)


def _limits(
    tool_name: str, tool_input: dict[str, Any], named: list[str], command: str | None, cwd: str
) -> Iterable[tuple[int, str]]:
    """Minimums and the floor: what no policy file can lower."""
    texts = [*named, *([command] if command else [])]
    if any(SECRET_PATHS.search(text) for text in texts) or redact.contains_secret(
        json.dumps(tool_input)
    ):
        yield 3, "floor: secrets"
    folder_too = tool_name in FOLDER_TOOLS
    if tool_name in READ_TOOLS | EDIT_TOOLS and any(not _inside(p, cwd, folder_too) for p in named):
        yield 2, "minimum: outside the project"
    if tool_name in EDIT_TOOLS:
        for path in named:
            parts = Path(path).parts
            for protected in PROTECTED_DIRS:
                depth = protected.count("/") + 1
                if any("/".join(parts[i : i + depth]) == protected for i in range(len(parts))):
                    agent = protected in (".claude", ".earshot")
                    effect = "change_agent_permissions" if agent else "protected path"
                    yield 3, f"floor: {effect} ({protected}/)"
            if parts and parts[-1] in PROTECTED_FILES:
                yield 3, f"floor: protected path ({parts[-1]})"
            if parts and parts[-1] in CONFIG_FILES:
                yield 2, f"minimum: build or test config ({parts[-1]})"
    if command is not None:
        if any(c in SHELL_SPECIALS for c in command):
            yield 2, "minimum: shell syntax"
        for pattern, effect in (
            (FORCE_PUSH, "force_push"),
            (DEFAULT_BRANCH_PUSH, "push_to_default_branch"),
            (RECURSIVE_DELETE, "delete_recursive"),
            (PIPE_TO_SHELL, "pipe_to_shell"),
            (DEPLOY, "deploy"),
            (AGENT_FILES, "change_agent_permissions"),
        ):
            if pattern.search(command):
                yield 3, f"floor: {effect}"
