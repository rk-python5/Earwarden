"""The safety stub (D-019): what voice may approve until Phase 2's policy engine replaces it.

Voice may approve only:

- a file edit or write inside the session's folder, except in `.git/`, `.claude/`, `.earshot/`,
  `.github/workflows/` or `.envrc`, and except build and test config
- a single test command (`pytest`, `uv run pytest`, `npm test`), with arguments but no chaining,
  pipes, redirection or substitution

Everything else goes to the screen. The policy engine that replaces this must never be looser.
"""

from __future__ import annotations

import posixpath
from typing import Any, NamedTuple

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
PROTECTED_DIRS = (".git", ".claude", ".earshot", ".github/workflows")
PROTECTED_FILES = {
    ".envrc",
    "conftest.py",
    "package.json",
    "Makefile",
    "pyproject.toml",
    "setup.py",
}
TEST_COMMANDS = (("pytest",), ("uv", "run", "pytest"), ("npm", "test"))
SHELL_SPECIALS = set(";&|<>`$()\n\r\\{}*?![]~'\"#")


class Verdict(NamedTuple):
    voice_ok: bool
    reason: str


def _inside(path: str, folder: str) -> str | None:
    """`path` relative to `folder`, or None if it's outside it."""
    full = posixpath.normpath(posixpath.join(folder, path))
    root = posixpath.normpath(folder)
    if full == root or not full.startswith(root.rstrip("/") + "/"):
        return None
    return full[len(root.rstrip("/")) + 1 :]


def _edit(tool_input: dict[str, Any], cwd: str) -> Verdict:
    path = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not isinstance(path, str) or not path:
        return Verdict(False, "edit without a file path")
    relative = _inside(path, cwd)
    if relative is None:
        return Verdict(False, "edit outside the project")
    parts = relative.split("/")
    for protected in PROTECTED_DIRS:
        depth = protected.count("/") + 1
        if any("/".join(parts[i : i + depth]) == protected for i in range(len(parts))):
            return Verdict(False, f"edit in {protected}/")
    if parts[-1] in PROTECTED_FILES:
        return Verdict(False, f"edit of {parts[-1]}")
    return Verdict(True, "edit inside the project")


def _test_command(tool_input: dict[str, Any]) -> Verdict:
    command = tool_input.get("command")
    if not isinstance(command, str) or not command.strip():
        return Verdict(False, "command missing")
    if any(c in SHELL_SPECIALS for c in command):
        return Verdict(False, "command with shell syntax")
    words = command.split()
    for prefix in TEST_COMMANDS:
        if tuple(words[: len(prefix)]) == prefix:
            return Verdict(True, "test command")
    return Verdict(False, "command not on the test list")


def judge(tool_name: str, tool_input: dict[str, Any], cwd: str) -> Verdict:
    if tool_name in EDIT_TOOLS:
        return _edit(tool_input, cwd)
    if tool_name == "Bash":
        return _test_command(tool_input)
    return Verdict(False, f"{tool_name} isn't approvable by voice yet")
