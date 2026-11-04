"""The template narrator: one short sentence per request, written by rules (Phase 1).

Six action families from the spec (git push, package install, file write or edit, delete, network
call, MCP tool), plus test runs and a fallback. Secrets are redacted before anything is said, and a
sentence longer than 25 words isn't spoken at all: the request waits on the screen instead.
"""

from __future__ import annotations

import shlex
from typing import Any, NamedTuple

from earshot.narrator import redact, spoken

MAX_WORDS = 25


class Narration(NamedTuple):
    text: str
    fits: bool  # False when the request is too long to say faithfully


def _words(command: str) -> list[str]:
    try:
        return shlex.split(command)
    except ValueError:
        return command.split()


def _git_push(session: str, words: list[str]) -> str:
    args = [w for w in words[2:] if not w.startswith("-") or w.startswith("+")]
    force = any(
        w in ("-f", "--force") or w.startswith("--force-with-lease") or w.startswith("+")
        for w in words[2:]
    )
    remote = args[0] if args else "its upstream"
    refs = [spoken.identifier(a.lstrip("+")) for a in args[1:]]
    what = " and ".join(refs) if refs else "the current branch"
    lease = any(w.startswith("--force-with-lease") for w in words[2:])
    tail = ", as a force push, with lease" if lease else ", as a force push" if force else ""
    return f"{session} wants to push {what} to {spoken.identifier(remote)}{tail}."


def _install(session: str, words: list[str]) -> str | None:
    starts = (
        ["pip", "install"],
        ["uv", "pip", "install"],
        ["uv", "add"],
        ["npm", "install"],
        ["pnpm", "add"],
        ["yarn", "add"],
        ["brew", "install"],
    )
    for start in starts:
        if words[: len(start)] == start:
            rest = words[len(start) :]
            packages = [spoken.package(w) for w in rest if not w.startswith("-")]
            index = [w for w in rest if w.startswith(("--index-url", "--extra-index-url", "-i"))]
            said = ", ".join(packages) if packages else "packages"
            extra = ", from a different index" if index else ""
            return f"{session} wants to install {said}{extra}."
    return None


def _delete(session: str, words: list[str]) -> str:
    recursive = any(w.startswith("-") and ("r" in w.lower()) for w in words[1:])
    targets = [spoken.identifier(w) for w in words[1:] if not w.startswith("-")]
    what = ", ".join(targets) if targets else "files"
    return f"{session} wants to delete {what}{', recursively' if recursive else ''}."


def _network(session: str, words: list[str]) -> str:
    urls = [w for w in words[1:] if "://" in w or w.startswith("www.")]
    sends = any(w in ("-d", "--data", "-F", "--form", "-T", "--upload-file") for w in words) or any(
        w in ("-X", "--request") and i + 1 < len(words) and words[i + 1].upper() != "GET"
        for i, w in enumerate(words)
    )
    where = spoken.domain(urls[0]) if urls else "the network"
    return f"{session} wants to {'send data to' if sends else 'fetch from'} {where}."


def _bash(session: str, command: str) -> str:
    words = _words(command)
    if not words:
        return f"{session} wants to run an empty command."
    if words[:2] == ["git", "push"]:
        return _git_push(session, words)
    installed = _install(session, words)
    if installed:
        return installed
    if words[0] == "rm":
        return _delete(session, words)
    if words[0] in ("curl", "wget"):
        return _network(session, words)
    if words[0] == "pytest" or words[:3] == ["uv", "run", "pytest"] or words[:2] == ["npm", "test"]:
        return f"{session} wants to run the tests."
    return f"{session} wants to run: {spoken.identifier(command)}."


def narrate(session: str, cwd: str, tool_name: str, tool_input: dict[str, Any]) -> Narration:
    """What to say about one request. Secrets are already replaced with "a secret value"."""
    who = spoken.identifier(session)
    if tool_name == "Bash":
        command = redact.redact(str(tool_input.get("command", "")), redact.SPOKEN)
        text = _bash(who, command)
    elif tool_name in ("Edit", "MultiEdit", "Write", "NotebookEdit"):
        target = str(tool_input.get("file_path") or tool_input.get("notebook_path") or "a file")
        verb = "write" if tool_name == "Write" else "edit"
        text = f"{who} wants to {verb} {spoken.path(target, cwd)}."
    elif tool_name in ("WebFetch", "WebSearch"):
        url = str(tool_input.get("url") or "")
        text = (
            f"{who} wants to fetch from {spoken.domain(url)}."
            if url
            else f"{who} wants to search the web."
        )
    elif tool_name.startswith("mcp__"):
        _, server, tool = [*tool_name.split("__", 2), "", ""][:3]
        text = f"{who} wants to use {spoken.identifier(tool)} from {spoken.identifier(server)}."
    else:
        text = f"{who} wants to use {spoken.identifier(tool_name)}."
    text = redact.redact(text, redact.SPOKEN)
    if len(text.split()) > MAX_WORDS:
        return Narration(f"{who} has a long request waiting.", fits=False)
    return Narration(text, fits=True)
