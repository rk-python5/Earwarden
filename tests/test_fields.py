"""Critical fields and the fidelity checker (Phase 2, milestone 3)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from earwarden.narrator import checker
from earwarden.narrator.templates import narrate
from earwarden.policy import engine, fields

CWD = "/Users/rehaan/code/api"


def say(tool: str, tool_input: dict[str, Any], cwd: str = CWD) -> str:
    narration = narrate("api", cwd, tool, tool_input, engine.judge(tool, tool_input, cwd))
    assert narration.fits, narration.problem
    return narration.text


@pytest.mark.parametrize(
    ("tool", "tool_input", "said"),
    [
        (
            "Bash",
            {"command": "uv run pytest -x && git push origin feature/login"},
            "api wants to run the tests, then push feature slash login to origin.",
        ),
        (
            "Bash",
            {"command": "pip install 'requests==2.32.3' httpx -i https://pypi.example.com/simple"},
            "api wants to install requests, version 2.32.3, httpx, "
            "from the index at example dot com.",
        ),
        (
            "Bash",
            {"command": "npm install"},
            "api wants to install the packages in package dot json.",
        ),
        ("Bash", {"command": "rm -rf build dist"}, "api wants to delete build, dist, recursively."),
        (
            "Bash",
            {"command": "curl -X DELETE https://api.example.com/v1/users/7"},
            "api wants to send a DELETE to example dot com.",
        ),
        (
            "Bash",
            {"command": "curl --json '{\"a\": 1}' https://hooks.slack.com/x"},
            "api wants to send data to slack dot com.",
        ),
        (
            "Bash",
            {"command": "git push origin :old-branch"},
            "api wants to delete old branch on origin.",
        ),
        (
            "mcp__github__create_issue",
            {"repo": "earwarden", "title": "A very long issue title that goes on"},
            "api wants to use create issue from github, on earwarden.",
        ),
        (
            "Read",
            {"file_path": "/etc/hosts"},
            "api wants to read hosts, in the etc folder, outside the project.",
        ),
        ("WebSearch", {"query": "x"}, "api wants to search the web."),
    ],
)
def test_sentences_say_every_critical_field(
    tool: str, tool_input: dict[str, Any], said: str
) -> None:
    assert say(tool, tool_input) == said


def test_a_bare_push_names_the_branch_it_really_pushes(tmp_path: Path) -> None:
    def git(*args: str) -> None:
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True)  # noqa: S607

    git("init", "-q", "-b", "feature/login")
    git("-c", "user.email=a@b", "-c", "user.name=a", "commit", "-q", "--allow-empty", "-m", "1")
    assert say("Bash", {"command": "git push"}, str(tmp_path)) == (
        "api wants to push feature slash login to origin."
    )


def test_pip_install_r_names_what_the_file_lists(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text(
        "# deps\nrequests==2.32.3\nnumpy>=2 ; python_version>'3'\n-e .\n"
    )
    assert say("Bash", {"command": "pip install -r requirements.txt"}, str(tmp_path)) == (
        "api wants to install requests, version 2.32.3, numpy, version 2 or so."
    )
    assert say("Bash", {"command": "pip install -r missing.txt"}, str(tmp_path)) == (
        "api wants to install the packages in missing dot t x t."
    )


def test_secrets_never_become_critical_fields() -> None:
    token = "ghp_" + "a1B2c3D4e5" * 4
    said = say("Bash", {"command": f"git push https://x:{token}@github.com/a/b main"})
    assert token not in said


# The checker


def actions(tool: str, tool_input: dict[str, Any]) -> list[fields.Action]:
    judgement = engine.judge(tool, tool_input, CWD)
    return fields.actions(tool, tool_input, CWD, judgement.bash)


def test_the_checker_catches_a_dropped_field() -> None:
    acts = actions("Bash", {"command": "git push --force origin feature"})
    result = checker.check("api wants to push feature to origin.", "api", acts)
    assert not result.ok
    assert result.missing == ("force: force push",)


def test_the_checker_catches_an_invented_detail() -> None:
    acts = actions("Bash", {"command": "git push origin feature"})
    result = checker.check("api wants to push feature to origin, then main.", "api", acts)
    assert not result.ok
    assert result.invented == ("main",)


def test_the_checker_passes_a_faithful_sentence() -> None:
    acts = actions("Bash", {"command": "git push origin feature"})
    assert checker.check("api wants to push feature to origin.", "api", acts).ok


# Every template passes the checker on a corpus of real requests

CORPUS: list[tuple[str, dict[str, Any]]] = [
    ("Bash", {"command": c})
    for c in (
        "pytest -q",
        "uv run pytest tests/test_app.py -x",
        "npm test",
        "git status",
        "git push",
        "git push -u origin feature/x",
        "git push --force-with-lease origin HEAD:release/1.2",
        "git push origin --delete stale",
        "git push --all",
        "pip install requests==2.32.3",
        "uv add 'httpx>=0.27' --dev",
        "npm install --save-dev typescript@5.4",
        "brew install jq",
        "rm notes.tmp",
        "rm -rf node_modules",
        "curl https://api.github.com/repos/a/b",
        "curl -sS -X POST -d @payload.json https://hooks.example.org/in",
        "wget https://example.com/file.tar.gz",
        "ls -la src",
        "cat README.md | head -20",
        "python3 manage.py migrate",
        "make build && make test",
        "docker compose up -d",
        "git commit -m \"$(cat <<'EOF'\nFix the parser\nEOF\n)\"",
        "echo $HOME",
    )
] + [
    ("Edit", {"file_path": f"{CWD}/src/api/routes.py", "old_string": "a", "new_string": "b"}),
    ("Write", {"file_path": "docs/guide.md", "content": "x"}),
    ("Write", {"file_path": "/Users/rehaan/.zshrc", "content": "x"}),
    ("MultiEdit", {"file_path": "src/app.py", "edits": []}),
    ("NotebookEdit", {"notebook_path": "analysis.ipynb"}),
    ("Read", {"file_path": "src/app.py"}),
    ("WebFetch", {"url": "https://docs.python.org/3/library/re.html", "prompt": "x"}),
    ("WebSearch", {"query": "python re module"}),
    ("mcp__linear__create_issue", {"title": "Fix login"}),
    ("mcp__github__push_files", {"files": []}),
    ("Task", {"description": "x"}),
]


@pytest.mark.parametrize(("tool", "tool_input"), CORPUS)
def test_every_template_passes_the_checker(tool: str, tool_input: dict[str, Any]) -> None:
    narration = narrate("api", CWD, tool, tool_input, engine.judge(tool, tool_input, CWD))
    assert narration.fits or narration.problem == "narrator: too long to say", narration.problem
