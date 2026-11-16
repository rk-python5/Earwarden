"""The policy engine: a tier for every request, from rules alone (Phase 2, milestones 1 and 2).

How a tier is chosen (the spec, with D-029). Each step can only raise what the last one gave,
except that a matching rule replaces the default:

1. A default per tool: reads and edits inside the project are tier 1; reads and edits outside it,
   unknown tools, and Bash commands no rule matches are tier 2 (P-02).
2. Rules: the spec's example rules, built in, then yours (`~/.earshot/policy.yaml`), which replace
   a built-in rule with the same id. A trusted repo policy counts as yours. If several rules
   match, the highest tier wins. A Bash command is split into the simple commands it runs
   (`bash.assess`), and each is matched on its own: `pytest && make deploy` isn't a test run.
3. An untrusted repo policy can only raise (P-11).
4. Minimums no file can lower: reads and edits outside the project, edits to build and test
   config, and any Bash command after build or test config was edited in the same session are at
   least tier 2 (P-01, P-02).
5. The never-by-voice floor is tier 3: secrets, the agent's and Earshot's own settings, protected
   paths, force pushes, pushes to the default branch, recursive deletes, piping into a shell,
   deploys, and any command that can't be read statically.

Tier 0 means tier 1 (P-02): nothing is approved without an answer. A policy file that can't be
read makes everything tier 3, so a broken file never loosens anything.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from typing import Any, NamedTuple

from earshot import contracts, paths
from earshot.narrator import redact
from earshot.policy import bash, fields, places
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
    bash: bash.Assessment | None = None  # what a Bash command was read as
    raised: str | None = None  # the risk gate's spoken reason, if it raised the tier (Phase 4)


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
    try:
        found = find_repo_policy(cwd)
        if found is not None:
            repo = load(found)
            repo_trusted = trusted(found, where.trusted_policies)
    except (PolicyError, OSError) as exc:
        errors.append(str(exc))
    for policy in (yours, repo):
        unknown = set(policy.never_by_voice) - set(FLOOR) if policy else set()
        if unknown:
            errors.append(f"unknown never_by_voice effects: {', '.join(sorted(unknown))}")
    return Policies(yours, repo, repo_trusted, tuple(errors))


def judge_built_in(request: contracts.ApprovalRequest, config_edited: bool = False) -> Judgement:
    """A tier from the built-in rules alone, with no policy files."""
    return judge(request.tool_name, request.tool_input, request.cwd, None, config_edited)


def judge_request(
    where: paths.Paths, request: contracts.ApprovalRequest, config_edited: bool = False
) -> Judgement:
    return judge_at(where, request.tool_name, request.tool_input, request.cwd, config_edited)


def judge_at(
    where: paths.Paths,
    tool_name: str,
    tool_input: dict[str, Any],
    cwd: str,
    config_edited: bool = False,
) -> Judgement:
    """A tier with the policy files as they are on disk now."""
    return judge(tool_name, tool_input, cwd, policies_for(where, cwd), config_edited)


def judge(
    tool_name: str,
    tool_input: dict[str, Any],
    cwd: str,
    policies: Policies | None = None,
    config_edited: bool = False,
) -> Judgement:
    """The tier for one request. `config_edited`: build or test config was edited this session."""
    policies = policies or Policies()
    if policies.errors:
        return Judgement(3, tuple(f"policy: {error}" for error in policies.errors), ())
    command = tool_input.get("command") if tool_name == "Bash" else None
    if command is not None and not isinstance(command, str):
        command = json.dumps(command)
    named = _paths(tool_name, tool_input, cwd)
    assessment: bash.Assessment | None = None
    limits: list[places.Limit] = []
    if command:
        try:
            assessment = bash.assess(command, cwd)
            limits += assessment.limits
        except Exception:  # a bug here must hand off, never approve
            limits.append((3, "unchecked: the command couldn't be read"))
    # Bash is matched one simple command at a time; other tools as a whole.
    texts: list[str | None] = [None]
    if tool_name == "Bash":
        texts = list(assessment.parts) if assessment and assessment.parts else [command]

    unknown_tool = policies.yours.defaults.unknown_tool if policies.yours else 2
    default_tier, default_why = _default(tool_name, named, command, unknown_tool)
    rules: list[str] = []
    critical: list[str] = []
    tiers: list[int] = []
    yours = list(_your_rules(policies))
    for text in texts:
        matched = [r for r in yours if _matches(r.match, tool_name, text, named)]
        if matched:
            tiers.append(max(r.tier for r in matched))
            rules += [f"rule {r.id}" for r in matched]
            critical += [field for r in matched for field in r.critical]
        else:
            tiers.append(default_tier)
            rules.insert(0, f"default: {default_why}")
        if policies.repo is not None and not policies.repo_trusted:
            for rule in policies.repo.rules:
                if rule.tier > tiers[-1] and _matches(rule.match, tool_name, text, named):
                    tiers[-1] = rule.tier
                    rules.append(f"repo rule {rule.id} (raises only, untrusted)")
    tier = max(tiers)

    limits += _limits(tool_name, tool_input, named, cwd)
    for words in assessment.commands if assessment else ():
        install = fields.parse_install(words, cwd)
        for hit in fields.lookalikes(install) if install else ():
            limits.append((3, f"minimum: {hit.name} looks like {hit.like} (P-09)"))
    if tool_name == "Bash" and config_edited:
        limits.append((2, "minimum: runs code after build or test config was edited (P-01)"))
    raised = [(m, why) for m, why in limits if m > tier]
    rules += [why for _, why in raised]  # each of these alone would raise the tier
    tier = max([tier, *(m for m, _ in raised)])
    return Judgement(
        max(tier, 1),
        tuple(dict.fromkeys(rules)),
        tuple(dict.fromkeys(critical)),
        assessment,
    )


def _paths(tool_name: str, tool_input: dict[str, Any], cwd: str) -> list[str]:
    """Every path the request names, made absolute against the session's folder."""
    found = [v for k in PATH_KEYS if isinstance(v := tool_input.get(k), str) and v]
    if not found and tool_name in FOLDER_TOOLS:
        found = [cwd]
    return [places.absolute(p, cwd) for p in found]


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
    tool_name: str, tool_input: dict[str, Any], named: list[str], cwd: str
) -> list[places.Limit]:
    """Minimums and the floor for the paths a request names, and secrets in its input."""
    limits: list[places.Limit] = []
    if any(places.secret(p) for p in named) or redact.contains_secret(json.dumps(tool_input)):
        limits.append((3, "floor: secrets"))
    if tool_name in EDIT_TOOLS:
        for path in named:
            limits += places.write_limits(path, cwd, cwd)
    elif tool_name in READ_TOOLS:
        folder_too = tool_name in FOLDER_TOOLS
        if any(not places.inside(p, cwd, folder_too) for p in named):
            limits.append((2, "minimum: outside the project"))
    return limits
