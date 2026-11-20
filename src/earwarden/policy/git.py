"""Git, resolved the way git itself would: aliases, and where a push really goes (P-01).

Command text can hide what a git command does. A bare `git push` pushes the current branch, so on
`main` it's a push to the default branch. `git sync` may be an alias for `push -f origin main`.
The resolver asks git, read-only and in the session's folder:

- `git config --get alias.NAME` to expand an alias (a `!` alias is a shell command)
- `git rev-parse` for the current branch and its upstream
- `git symbolic-ref refs/remotes/REMOTE/HEAD` for the remote's default branch, falling back to
  `main` and `master`

If git can't answer, a push whose target can't be told is reported as unresolved (tier 3).
"""

from __future__ import annotations

import os
import subprocess
from typing import NamedTuple

TIMEOUT_S = 2.0
FALLBACK_DEFAULTS = frozenset({"main", "master"})
# Git ignores an alias that shadows one of its own commands, so these never expand.
BUILT_IN = frozenset(
    [
        "add",
        "am",
        "annotate",
        "apply",
        "archive",
        "bisect",
        "blame",
        "branch",
        "bundle",
        "cat-file",
        "check-ignore",
        "checkout",
        "cherry",
        "cherry-pick",
        "citool",
        "clean",
        "clone",
        "commit",
        "config",
        "count-objects",
        "describe",
        "diff",
        "diff-files",
        "diff-index",
        "diff-tree",
        "difftool",
        "fetch",
        "filter-branch",
        "format-patch",
        "fsck",
        "gc",
        "grep",
        "gui",
        "help",
        "init",
        "instaweb",
        "log",
        "ls-files",
        "ls-remote",
        "ls-tree",
        "merge",
        "merge-base",
        "mergetool",
        "mv",
        "notes",
        "pull",
        "push",
        "range-diff",
        "rebase",
        "reflog",
        "remote",
        "repack",
        "replace",
        "request-pull",
        "reset",
        "restore",
        "rev-list",
        "rev-parse",
        "revert",
        "rm",
        "send-email",
        "shortlog",
        "show",
        "show-branch",
        "show-ref",
        "sparse-checkout",
        "stash",
        "status",
        "submodule",
        "switch",
        "symbolic-ref",
        "tag",
        "update-index",
        "update-ref",
        "verify-commit",
        "verify-tag",
        "whatchanged",
        "worktree",
        "write-tree",
        "maintenance",
    ]
)
# Global options that take a value as the next word.
VALUED = frozenset({"-C", "-c", "--git-dir", "--work-tree", "--namespace"})


class Invocation(NamedTuple):
    folder: str  # where the command runs, after any `-C`
    words: tuple[str, ...]  # the subcommand and its arguments, aliases expanded
    config_override: bool  # `-c`, `--git-dir`, `--work-tree` or `--exec-path` were used
    shell_alias: str | None  # a `!` alias: the shell command it runs


class Push(NamedTuple):
    remote: str
    branches: tuple[str, ...]  # destination branches
    deletes: tuple[str, ...]  # remote branches it deletes
    force: bool
    everything: bool  # --all, --branches or --mirror
    defaults: frozenset[str]  # the remote's default branch, as best known
    unresolved: str | None  # why the target can't be told, if it can't


def run(folder: str, *args: str) -> str | None:
    """A read-only git query in `folder`, or None if git can't answer."""
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"}
    try:
        done = subprocess.run(  # noqa: S603 - git with fixed, read-only queries
            ["git", "-C", folder, "-c", "core.fsmonitor=false", *args],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=TIMEOUT_S,
            check=False,
            env=env,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def resolve(words: tuple[str, ...], cwd: str) -> Invocation:
    """`git` and its arguments (without the leading `git`), with `-C` and aliases resolved."""
    folder, override, i = cwd, False, 0
    while i < len(words) and words[i].startswith("-"):
        option, _, inline = words[i].partition("=")
        value = inline or (words[i + 1] if option in VALUED and i + 1 < len(words) else "")
        if option in VALUED and not inline:
            i += 1
        if option == "-C" and value:
            folder = os.path.normpath(os.path.join(folder, value))  # noqa: PTH118
        elif option in VALUED or option == "--exec-path":
            override = True
        i += 1
    rest = words[i:]
    for _ in range(5):  # aliases of aliases, a few deep
        if not rest or rest[0] in BUILT_IN:
            break
        alias = run(folder, "config", "--get", f"alias.{rest[0]}")
        if alias is None:
            break
        if alias.startswith("!"):
            return Invocation(folder, rest, override, alias[1:] + " " + " ".join(rest[1:]))
        rest = (*alias.split(), *rest[1:])
    return Invocation(folder, rest, override, None)


def push(args: tuple[str, ...], folder: str) -> Push:
    """Where `git push ARGS` would go, run in `folder`."""
    force = everything = delete = False
    positional: list[str] = []
    i = 0
    while i < len(args):
        word = args[i]
        if word == "--":
            positional += args[i + 1 :]
            break
        if word.startswith("--"):
            name = word.partition("=")[0]
            force |= name in ("--force", "--force-with-lease", "--force-if-includes")
            everything |= name in ("--all", "--branches", "--mirror")
            delete |= name == "--delete"
            if name in ("--push-option", "--repo", "--receive-pack", "--exec") and "=" not in word:
                i += 1
        elif word.startswith("-") and len(word) > 1:
            force |= "f" in word[1:]
            delete |= "d" in word[1:]
            if word[1:].endswith("o"):
                i += 1  # -o takes a value
        else:
            positional.append(word)
        i += 1

    remote = positional[0] if positional else ""
    refspecs = positional[1:]
    current = run(folder, "rev-parse", "--abbrev-ref", "HEAD")
    upstream = run(folder, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    if not remote:
        remote = upstream.split("/", 1)[0] if upstream and "/" in upstream else "origin"
    head = run(folder, "symbolic-ref", "--short", f"refs/remotes/{remote}/HEAD")
    defaults = FALLBACK_DEFAULTS | ({head.split("/", 1)[1]} if head and "/" in head else set())

    branches: list[str] = []
    deletes: list[str] = []
    unresolved = None
    for spec in refspecs:
        if spec.startswith("+"):
            force, spec = True, spec[1:]
        source, colon, destination = spec.partition(":")
        if colon and not source:
            deletes.append(_branch(destination, current))
        elif delete:
            deletes.append(_branch(destination or source, current))
        else:
            target = _branch(destination or source, current)
            if target == "HEAD":
                unresolved = "a push from a detached HEAD"
            branches.append(target)
    if not refspecs and not everything:
        if upstream and "/" in upstream and upstream.split("/", 1)[0] == remote:
            branches.append(upstream.split("/", 1)[1])
        elif current and current != "HEAD":
            branches.append(current)
        else:
            unresolved = "can't tell which branch a bare git push sends"
    found = frozenset(defaults)
    return Push(remote, tuple(branches), tuple(deletes), force, everything, found, unresolved)


def _branch(ref: str, current: str | None) -> str:
    if ref == "HEAD" and current:
        return current
    for prefix in ("refs/heads/", "heads/"):
        if ref.startswith(prefix):
            return ref[len(prefix) :]
    return ref
