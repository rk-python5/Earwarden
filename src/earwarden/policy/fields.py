"""Critical fields: what the narrator must say about a request (Phase 2, milestone 3).

The spec's table, one action per simple command (or per tool call):

    git push          the remote, the branch it really pushes, force
    package install   every package and its version pin, a non-default index
    write or edit     the file and its folder, whether it's outside the project
    delete            the targets, recursive
    network call      the domain, a method other than GET, whether data is sent
    MCP tool          the server, the tool, the main argument

Values come from the policy engine's reading of the request, so a bare `git push` names the branch
it really pushes, and `pip install -r requirements.txt` names what's in the file. Every value is
redacted before it's made speakable, so a secret can't become a critical field.
"""

from __future__ import annotations

import posixpath
from pathlib import Path
from typing import Any, NamedTuple

from earwarden.narrator import redact, spoken
from earwarden.policy import bash, git, lookalike, places
from earwarden.policy.shell import UNSEEN

MAX_REQUIREMENTS_BYTES = 64_000


class Field(NamedTuple):
    name: str
    spoken: str  # the words the sentence must contain


class Action(NamedTuple):
    kind: str  # push, install, delete, network, write, edit, read, mcp, tests, run, search, use
    fields: tuple[Field, ...]
    detail: dict[str, Any]  # what the narrator needs to phrase it


def say(text: str) -> str:
    """A value made safe to speak: secrets redacted, run-time values named as such."""
    return redact.redact(text, redact.SPOKEN).replace(UNSEEN, "something")


INSTALLS: dict[tuple[str, ...], frozenset[str]] = {
    # the command, and its options that take a value
    ("pip", "install"): frozenset(
        {
            "-r",
            "--requirement",
            "-c",
            "--constraint",
            "-i",
            "--index-url",
            "--extra-index-url",
            "-f",
            "--find-links",
            "-t",
            "--target",
            "--prefix",
            "--root",
            "--python-version",
            "--platform",
            "--implementation",
            "--abi",
            "--src",
            "--upgrade-strategy",
        }
    ),
    ("uv", "pip", "install"): frozenset(
        {
            "-r",
            "--requirement",
            "-c",
            "--constraint",
            "-i",
            "--index-url",
            "--extra-index-url",
            "--index",
            "-f",
            "--find-links",
            "-p",
            "--python",
            "--target",
            "--prefix",
        }
    ),
    ("uv", "add"): frozenset(
        {
            "-r",
            "--requirements",
            "--index",
            "--default-index",
            "--group",
            "--optional",
            "-p",
            "--python",
            "--extra",
        }
    ),
    ("npm", "install"): frozenset({"--registry", "--prefix", "-w", "--workspace"}),
    ("npm", "i"): frozenset({"--registry", "--prefix", "-w", "--workspace"}),
    ("npm", "add"): frozenset({"--registry", "--prefix", "-w", "--workspace"}),
    ("pnpm", "add"): frozenset({"--registry", "--filter", "-F"}),
    ("pnpm", "install"): frozenset({"--registry", "--filter", "-F"}),
    ("yarn", "add"): frozenset({"--registry"}),
    ("brew", "install"): frozenset(),
    ("pipx", "install"): frozenset({"--index-url", "--python", "--pip-args"}),
    ("poetry", "add"): frozenset({"--source", "-G", "--group"}),
    ("cargo", "add"): frozenset({"--registry", "--path", "--git", "--branch", "--tag", "--rev"}),
    ("gem", "install"): frozenset({"--source", "-s", "-v", "--version"}),
}
INDEX_OPTIONS = {
    "-i",
    "--index-url",
    "--extra-index-url",
    "--index",
    "--default-index",
    "--registry",
    "--source",
    "-s",
}
REQUIREMENT_OPTIONS = {"-r", "--requirement", "--requirements"}
TEST_COMMANDS = (("pytest",), ("uv", "run", "pytest"), ("npm", "test"), ("python", "-m", "pytest"))
DATA_FLAGS = {
    "-d",
    "--data",
    "--data-raw",
    "--data-binary",
    "--data-urlencode",
    "--json",
    "-F",
    "--form",
    "-T",
    "--upload-file",
    "--post-data",
    "--post-file",
    "--body-data",
    "--body-file",
}


def actions(
    tool_name: str, tool_input: dict[str, Any], cwd: str, assessment: bash.Assessment | None
) -> list[Action]:
    """What a request does, as the spec's action families, each with its critical fields."""
    if tool_name == "Bash":
        if assessment is None or not assessment.commands:
            return [_run(str(tool_input.get("command", "")))]
        pushes = iter(assessment.pushes)
        return [_command(words, cwd, pushes) for words in assessment.commands]
    if tool_name in ("Edit", "MultiEdit", "Write", "NotebookEdit"):
        target = tool_input.get("file_path") or tool_input.get("notebook_path")
        kind = "write" if tool_name == "Write" else "edit"
        return [_file(kind, target if isinstance(target, str) and target else "a file", cwd)]
    if tool_name in ("Read", "NotebookRead"):
        target = tool_input.get("file_path") or tool_input.get("notebook_path") or "a file"
        return [_file("read", str(target), cwd)]
    if tool_name == "WebFetch" and isinstance(url := tool_input.get("url"), str) and url:
        domain = spoken.domain(say(url))
        detail = {"domain": domain, "verb": "fetch from"}
        return [Action("network", (Field("domain", domain),), detail)]
    if tool_name == "WebSearch":
        return [Action("search", (), {})]
    if tool_name.startswith("mcp__"):
        return [_mcp(tool_name, tool_input)]
    return [Action("use", (Field("tool", spoken.identifier(tool_name)),), {"tool": tool_name})]


def _command(words: tuple[str, ...], cwd: str, pushes: Any) -> Action:
    if words[:2] == ("git", "push"):
        push: git.Push | None = next(pushes, None)
        return _push(push, words)
    install = parse_install(words, cwd)
    if install is not None:
        return _install(install)
    if words[0] == "rm":
        return _delete(words[1:], cwd)
    if words[0] in ("curl", "wget", "http", "xh"):
        return _network(words)
    if any(words[: len(t)] == t for t in TEST_COMMANDS):
        return Action("tests", (), {})
    return _run(" ".join(words))


def _run(command: str) -> Action:
    said = spoken.identifier(say(command))
    return Action("run", (Field("command", said),) if said else (), {"command": said})


def _push(push: git.Push | None, words: tuple[str, ...]) -> Action:
    if push is None:  # the engine didn't resolve it: say what was typed
        push = git.push(words[2:], "/nonexistent")
    remote = spoken.identifier(say(push.remote or "its upstream"))
    if push.everything:
        branches = ["every branch"]
    elif push.branches:
        branches = [spoken.identifier(say(b)) for b in push.branches]
    elif push.deletes:
        branches = []  # it only deletes
    else:
        branches = ["the current branch"]
        remote = remote if push.remote and push.remote != "origin" else "its upstream"
    fields = [Field("remote", remote), *(Field("branch", b) for b in branches)]
    if push.force:
        fields.append(Field("force", "force push"))
    deletes = [spoken.identifier(say(b)) for b in push.deletes]
    fields += [Field("deletes", d) for d in deletes]
    detail = {"remote": remote, "branches": branches, "force": push.force, "deletes": deletes}
    return Action("push", tuple(fields), detail)


class Install(NamedTuple):
    manager: str
    registry: str | None  # "pypi" or "npm", for the lookalike check
    packages: tuple[str, ...]  # requirement specs, including those a requirements file lists
    unread: tuple[str, ...]  # requirements files that couldn't be read
    index_url: str | None  # a non-default index or registry


def parse_install(words: tuple[str, ...], cwd: str) -> Install | None:
    """The packages an install command asks for, or None if `words` isn't an install."""
    start = next((s for s in INSTALLS if words[: len(s)] == s), None)
    if start is None:
        return None
    valued = INSTALLS[start]
    args = words[len(start) :]
    packages: list[str] = []
    files: list[str] = []
    index: str | None = None
    i = 0
    while i < len(args):
        word = args[i]
        option, _, inline = word.partition("=")
        if word.startswith("-") and (option in valued or inline):
            value = inline or (args[i + 1] if i + 1 < len(args) else "")
            if option in INDEX_OPTIONS:
                index = value
            elif option in REQUIREMENT_OPTIONS:
                files.append(value)
            i += 1 if inline else 2
            continue
        if not word.startswith("-"):
            packages.append(word)
        i += 1
    unread: list[str] = []
    for name in files:
        listed = _requirements(name, cwd)
        if listed is None:
            unread.append(name)
        else:
            packages += listed
    registry = lookalike.MANAGERS.get(start[0])
    return Install(start[0], registry, tuple(packages), tuple(unread), index)


def lookalikes(install: Install) -> list[lookalike.Lookalike]:
    if install.registry is None:
        return []
    found = (
        lookalike.check(lookalike.requirement_name(spec, install.registry), install.registry)
        for spec in install.packages
    )
    return [hit for hit in found if hit is not None]


def _install(install: Install) -> Action:
    flagged = {hit.name: hit.like for hit in lookalikes(install)}
    said = []
    for spec in install.packages:
        name = lookalike.requirement_name(spec, install.registry or "pypi")
        if name in flagged:  # spelled out, so you hear exactly what it is
            said.append(
                f"{spoken.spell(say(name))}, which looks like {spoken.identifier(flagged[name])}"
            )
        else:
            said.append(spoken.package(say(spec)))
    said += [
        f"the packages in {spoken.file_name(posixpath.basename(say(f)))}" for f in install.unread
    ]
    if not said and install.manager in ("npm", "pnpm", "yarn"):
        said = ["the packages in package dot json"]
    fields = [Field("package", s) for s in said]
    detail: dict[str, Any] = {"packages": said, "index": None}
    if install.index_url:
        detail["index"] = spoken.domain(say(install.index_url))
        fields.append(Field("index", detail["index"]))
    return Action("install", tuple(fields), detail)


def _requirements(name: str, cwd: str) -> list[str] | None:
    """The packages a requirements file lists, or None if it can't be read."""
    if UNSEEN in name:
        return None
    try:
        text = Path(places.absolute(name, cwd)).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    found = []
    for line in text[:MAX_REQUIREMENTS_BYTES].splitlines():
        line = line.split("#", 1)[0].strip()
        if line and not line.startswith("-"):
            found.append(line.split(";", 1)[0].strip())
    return found


def _delete(args: tuple[str, ...], cwd: str) -> Action:
    recursive = any(
        a == "--recursive" or (a.startswith("-") and not a.startswith("--") and "r" in a.lower())
        for a in args
    )
    targets = [spoken.path(say(a), cwd) for a in args if not a.startswith("-")] or ["files"]
    fields = [Field("target", t) for t in targets]
    if recursive:
        fields.append(Field("recursive", "recursively"))
    return Action("delete", tuple(fields), {"targets": targets, "recursive": recursive})


def _network(words: tuple[str, ...]) -> Action:
    urls = [w for w in words[1:] if "://" in w or w.startswith("www.")]
    method = "GET"
    sends = False
    for i, word in enumerate(words):
        option, equals, value = word.partition("=")
        if option in ("-X", "--request", "--method"):
            method = (value if equals else words[i + 1] if i + 1 < len(words) else "GET").upper()
        sends |= option in DATA_FLAGS
    sends |= method in ("POST", "PUT", "PATCH")
    if method == "DELETE":
        verb = "send a DELETE to"
    elif sends:
        verb = "send data to"
    elif method not in ("GET", "HEAD"):
        verb = f"send a {method} to"
    else:
        verb = "fetch from"
    domain = spoken.domain(say(urls[0])) if urls else "the network"
    fields = [Field("domain", domain)]
    if verb != "fetch from":
        fields.append(Field("method", verb))
    return Action("network", tuple(fields), {"domain": domain, "verb": verb})


def _file(kind: str, target: str, cwd: str) -> Action:
    said = spoken.path(say(target), cwd)
    name = said.split(",", 1)[0]
    fields = [Field("file", name)]
    if ", in the " in said:
        fields.append(Field("folder", said.split(", in the ", 1)[1].split(",", 1)[0]))
    if said.endswith("outside the project"):
        fields.append(Field("outside", "outside the project"))
    return Action(kind, tuple(fields), {"path": said})


def _mcp(tool_name: str, tool_input: dict[str, Any]) -> Action:
    _, server, tool = [*tool_name.split("__", 2), "", ""][:3]
    fields = [Field("server", spoken.identifier(server)), Field("tool", spoken.identifier(tool))]
    argument = next((v for v in tool_input.values() if isinstance(v, str) and v.strip()), None)
    said = spoken.identifier(say(argument)) if argument else ""
    if said and len(said.split()) <= 6:
        fields.append(Field("argument", said))
    else:
        said = ""
    detail = {"server": fields[0].spoken, "tool": fields[1].spoken, "argument": said}
    return Action("mcp", tuple(fields), detail)
