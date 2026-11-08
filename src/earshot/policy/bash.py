"""Judging a Bash command: every simple command it runs, and what each one does (milestone 2).

The command is split by `shell.parse`. Each simple command is then read for what it does:

- Wrappers are seen through: `env`, `command`, `exec`, `nohup`, `time`, `nice`, `timeout`,
  `stdbuf`, `caffeinate`, `xargs`, `watch`, and `sudo` or `doas`, which also make it tier 3.
- `bash -c '...'` and its kin are parsed in turn. A shell or interpreter that reads its program
  from a pipe, heredoc or here-string is piping into a shell (tier 3).
- Git goes through `git.resolve` and `git.push`: aliases, `-C`, where a push really goes (P-01).
- Recursive deletes, deploys and publishes, and anything that writes into protected or outside
  places, or touches secrets or the agent's own settings, raise the tier (`places`).
- `cd` is followed, so later relative paths are judged where they really point.

The result is the text of each command as rules see it ("git push origin main", program names
without their folder) and the limits found. Rules match each part; the highest tier wins.
"""

from __future__ import annotations

import re
from typing import NamedTuple

from earshot.policy import git, places, shell
from earshot.policy.places import Limit

SHELLS = {"sh", "bash", "zsh", "dash", "ksh", "fish", "csh", "tcsh"}
INTERPRETERS = SHELLS | {
    "python",
    "python3",
    "perl",
    "ruby",
    "node",
    "php",
    "osascript",
    "pwsh",
    "deno",
    "bun",
    "lua",
    "tclsh",
    "Rscript",
}
CODE_FLAGS = {"-c", "-e", "-m", "--command", "--eval", "-E"}
READERS = {
    "cat",
    "less",
    "more",
    "head",
    "tail",
    "ls",
    "grep",
    "rg",
    "wc",
    "file",
    "stat",
    "diff",
    "bat",
    "find",
    "tree",
    "du",
}
# Wrapper programs, and their options that take a value.
WRAPPERS: dict[str, frozenset[str]] = {
    "env": frozenset({"-u", "--unset", "-C", "--chdir"}),
    "command": frozenset(),
    "builtin": frozenset(),
    "exec": frozenset({"-a"}),
    "nohup": frozenset(),
    "time": frozenset(),
    "nice": frozenset({"-n"}),
    "caffeinate": frozenset({"-t", "-w"}),
    "timeout": frozenset({"-s", "--signal", "-k", "--kill-after"}),
    "stdbuf": frozenset({"-i", "-o", "-e"}),
    "xargs": frozenset({"-I", "-n", "-P", "-L", "-d", "-E", "-s", "-a"}),
    "sudo": frozenset({"-u", "-g", "-h", "-p", "-C", "-U", "-r", "-t", "-D"}),
    "doas": frozenset({"-u", "-C"}),
    "watch": frozenset({"-n", "--interval", "-d"}),
}
DEPLOYS: dict[str, frozenset[str]] = {
    "terraform": frozenset({"apply", "destroy", "import"}),
    "tofu": frozenset({"apply", "destroy"}),
    "kubectl": frozenset(
        {
            "apply",
            "delete",
            "create",
            "replace",
            "patch",
            "rollout",
            "scale",
            "edit",
            "set",
            "drain",
        }
    ),
    "helm": frozenset({"install", "upgrade", "uninstall", "rollback", "delete"}),
    "fly": frozenset({"deploy"}),
    "flyctl": frozenset({"deploy"}),
    "cdk": frozenset({"deploy", "destroy"}),
    "serverless": frozenset({"deploy", "remove"}),
    "sls": frozenset({"deploy", "remove"}),
    "firebase": frozenset({"deploy"}),
    "netlify": frozenset({"deploy"}),
    "eb": frozenset({"deploy"}),
    "npm": frozenset({"publish", "unpublish", "deprecate"}),
    "pnpm": frozenset({"publish"}),
    "yarn": frozenset({"publish", "npm"}),
    "twine": frozenset({"upload"}),
    "poetry": frozenset({"publish"}),
    "uv": frozenset({"publish"}),
    "cargo": frozenset({"publish", "yank"}),
    "gem": frozenset({"push", "yank"}),
    "docker": frozenset({"push"}),
}
GH_DEPLOYS = {
    "release": {"create", "delete", "upload", "edit"},
    "repo": {"delete", "archive"},
    "pr": {"merge"},
    "workflow": {"run"},
}
CLOUD_VERBS = re.compile(r"deploy|delete|destroy|terminate|remove")
MAX_DEPTH = 4


class Assessment(NamedTuple):
    parts: tuple[str, ...]  # each simple command, as rules see it
    limits: tuple[Limit, ...]  # minimums and floor effects found
    pushes: tuple[git.Push, ...]  # every git push, resolved
    commands: tuple[tuple[str, ...], ...] = ()  # each part's words, for the narrator


class _Found:
    """What reading a command turns up, gathered across nested commands."""

    def __init__(self) -> None:
        self.parts: list[str] = []
        self.limits: list[Limit] = []
        self.pushes: list[git.Push] = []
        self.commands: list[tuple[str, ...]] = []

    def add(self, other: Assessment) -> None:
        self.parts += other.parts
        self.limits += other.limits
        self.pushes += other.pushes
        self.commands += other.commands

    def done(self) -> Assessment:
        limits = tuple(dict.fromkeys(self.limits))
        return Assessment(tuple(self.parts), limits, tuple(self.pushes), tuple(self.commands))


def assess(command: str, cwd: str, project: str | None = None, depth: int = 0) -> Assessment:
    """Read `command`, run in `cwd`, inside the session's `project` folder."""
    project = project or cwd
    if depth > MAX_DEPTH:
        return Assessment((), ((3, "unchecked: commands nested too deeply"),), ())
    script = shell.parse(command)
    found = _Found()
    found.limits += [(3, f"unchecked: {why}") for why in script.unchecked]
    here: str | None = cwd  # None once a `cd` goes somewhere that can't be read in advance
    for simple in script.commands:
        where = here or project
        for target in simple.writes:
            found.limits += places.write_limits(target if here else shell.UNSEEN, where, project)
        if any(places.secret(source) for source in simple.reads):
            found.limits.append((3, "floor: secrets"))
        words, wrapped = _unwrap(simple.words)
        found.limits += wrapped.limits
        if wrapped.watched is not None:
            found.add(assess(wrapped.watched, where, project, depth + 1))
        if not words:
            continue
        program, args = _program(words[0]), words[1:]
        if program in ("cd", "pushd"):
            target = args[0] if args else "~"
            unseen = shell.UNSEEN in target or target == "-"
            here = None if unseen else places.absolute(target, where)
            continue
        _judge(program, args, simple, where, project, depth, found)
    return found.done()


class _Unwrapped(NamedTuple):
    limits: list[Limit]
    watched: str | None  # `watch` runs its arguments as a shell command


def _program(word: str) -> str:
    return word.rsplit("/", 1)[-1] if "/" in word and not word.endswith("/") else word


def _unwrap(words: tuple[str, ...]) -> tuple[tuple[str, ...], _Unwrapped]:
    limits: list[Limit] = []
    while words and _program(words[0]) in WRAPPERS:
        wrapper = _program(words[0])
        valued = WRAPPERS[wrapper]
        if wrapper in ("sudo", "doas"):
            limits.append((3, "minimum: runs as root"))
        i = 1
        while i < len(words) and words[i].startswith("-") and words[i] != "-":
            if words[i] == "--":
                i += 1
                break
            if wrapper == "env" and words[i] in ("-S", "--split-string"):
                limits.append((3, "unchecked: env -S"))
            i += 2 if words[i] in valued else 1
        if wrapper == "env":
            while i < len(words) and shell.ASSIGNMENT.match(words[i]):
                i += 1
        if wrapper == "timeout" and i < len(words):
            i += 1  # the duration
        if wrapper == "watch":
            return (), _Unwrapped(limits, " ".join(words[i:]))
        words = words[i:]
    return words, _Unwrapped(limits, None)


def _judge(
    program: str,
    args: tuple[str, ...],
    simple: shell.Simple,
    cwd: str,
    project: str,
    depth: int,
    found: _Found,
) -> None:
    """One simple command: its text for rules, its limits, and any command it runs in turn."""
    words: tuple[str, ...] | None = (program, *args)  # None: a wrapper, judged by what it runs
    limits: list[Limit] = []
    if program in INTERPRETERS:
        code = _code_argument(program, args)
        if code is not None and program in SHELLS:
            found.add(assess(code, cwd, project, depth + 1))
            words = None
        elif code is None and simple.stdin and not _script_argument(args):
            limits.append((3, "floor: pipe_to_shell"))
    elif program == "git":
        invocation = git.resolve(args, cwd)
        words = ("git", *invocation.words)
        if invocation.config_override:
            limits.append((3, "minimum: git -c, or git pointed at another repository (P-01)"))
        if invocation.shell_alias is not None:
            found.add(assess(invocation.shell_alias, invocation.folder, project, depth + 1))
        elif invocation.words[:1] == ("config",):
            limits.append((3, "minimum: git config (P-01)"))
        elif invocation.words[:1] == ("push",):
            push = git.push(invocation.words[1:], invocation.folder)
            found.pushes.append(push)
            limits += _push_limits(push)
    elif program in ("rm", "find") and _recursive_delete(program, args):
        limits.append((3, "floor: delete_recursive"))
    if _deploys(program, args):
        limits.append((3, "floor: deploy"))

    for target in _written(program, args):
        limits += places.write_limits(target, cwd, project)
    for arg in args:
        if places.secret(arg):
            limits.append((3, "floor: secrets"))
        agent = places.agent_files(places.absolute(arg, cwd)) if not arg.startswith("-") else None
        if agent is not None and program not in READERS:
            limits.append((3, f"floor: change_agent_permissions ({agent})"))
    if words is not None:
        found.parts.append(" ".join(words))
        found.commands.append(words)
    found.limits += limits


def _code_argument(program: str, args: tuple[str, ...]) -> str | None:
    """The program text passed with `-c` (shells) or `-e`/`-c` (interpreters), if any."""
    for i, arg in enumerate(args):
        if arg in CODE_FLAGS or (program in SHELLS and re.fullmatch(r"-[a-z]*c[a-z]*", arg)):
            return args[i + 1] if i + 1 < len(args) else ""
        if not arg.startswith("-"):
            return None
    return None


def _script_argument(args: tuple[str, ...]) -> bool:
    """Whether the interpreter runs a script file rather than reading its program from stdin."""
    return any(not a.startswith("-") for a in args)


def _push_limits(push: git.Push) -> list[Limit]:
    limits: list[Limit] = []
    if push.force:
        limits.append((3, "floor: force_push"))
    if push.everything:
        limits.append((3, "floor: push_to_default_branch (every branch)"))
    if any(b in push.defaults for b in (*push.branches, *push.deletes)):
        limits.append((3, "floor: push_to_default_branch"))
    if push.unresolved:
        limits.append((3, f"unchecked: {push.unresolved}"))
    return limits


def _recursive_delete(program: str, args: tuple[str, ...]) -> bool:
    if program == "rm":
        for arg in args:
            if arg == "--":
                break
            if arg == "--recursive" or re.fullmatch(r"-[a-zA-Z]*[rR][a-zA-Z]*", arg):
                return True
        return False
    return "-delete" in args or any(
        a in ("-exec", "-execdir", "-ok") and _program(args[i + 1]) == "rm"
        for i, a in enumerate(args[:-1])
    )


def _deploys(program: str, args: tuple[str, ...]) -> bool:
    if program in DEPLOYS and any(a in DEPLOYS[program] for a in args[:3]):
        return True
    if program == "vercel":
        return "--prod" in args or "--production" in args
    if program == "gh" and len(args) >= 2:
        return args[1] in GH_DEPLOYS.get(args[0], set())
    if program in ("aws", "gcloud", "az"):
        return any(CLOUD_VERBS.search(a) for a in args if not a.startswith("-"))
    return False


def _written(program: str, args: tuple[str, ...]) -> list[str]:
    """Files a command writes, besides its redirections."""
    positional = [a for a in args if not a.startswith("-")]
    if program == "tee":
        return positional
    if program in ("cp", "mv", "install", "ln", "rsync", "scp") and len(positional) >= 2:
        for i, arg in enumerate(args[:-1]):
            if arg in ("-t", "--target-directory"):
                return [args[i + 1]]
        return [positional[-1]]
    if program in ("touch", "mkdir", "truncate", "chmod", "chown", "rm", "rmdir", "unlink"):
        return positional[1:] if program in ("chmod", "chown") else positional
    if program == "dd":
        return [a[3:] for a in args if a.startswith("of=")]
    if program == "sed" and any(a == "--in-place" or a.startswith("-i") for a in args):
        return positional[1:]
    if program == "curl":
        return [args[i + 1] for i, a in enumerate(args[:-1]) if a in ("-o", "--output")]
    if program == "wget":
        return [args[i + 1] for i, a in enumerate(args[:-1]) if a in ("-O", "--output-document")]
    return []
