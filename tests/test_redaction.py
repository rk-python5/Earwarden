"""Redaction against a corpus: no real-looking key is ever spoken or logged (Phase 2, milestone 3).

The keys are fakes, built from pieces at run time so no whole key sits in the source.
"""

from __future__ import annotations

import json

import pytest

from earwarden.narrator import redact
from earwarden.narrator.templates import narrate
from earwarden.policy import engine

CWD = "/Users/rehaan/code/api"
MIXED = "a1B2c3D4e5F6g7H8i9J0"  # 20 characters of mixed case and digits

SECRETS = [
    "AKIA" + "QWERTYUIOPASDFGH",
    "gh" + "p_" + MIXED * 2,
    "github" + "_pat_" + MIXED * 3,
    "gl" + "pat-" + MIXED,
    "sk-" + "ant-api03-" + MIXED * 2,
    "sk-" + "proj-" + MIXED * 2,
    "xo" + "xb-" + "123456789012-" + MIXED,
    "xa" + "pp-1-" + MIXED,
    "sk" + "_live_" + MIXED * 2,
    "rk" + "_test_" + MIXED,
    "AI" + "za" + "SyD" + MIXED + "kLmNoPqRsTuVw",
    "SG" + "." + MIXED + "." + MIXED * 2,
    "np" + "m_" + MIXED + "a1B2c3D4e5F6g7H8",
    "py" + "pi-" + "AgEIcHlwaS5vcmc" + MIXED * 3,
    "hf" + "_" + MIXED + "kLmNoPqRsTuVwX",
    "SK" + "0123456789abcdef0123456789abcdef",
    "ey"
    + "JhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
    "Q2xhdWRlIGlzIHRoZSBiZXN0IGFzc2lzdGFudDEyMzQ1Ng==",
]
# Secrets that only an assignment or an option reveals, and what must be hidden in each.
IN_CONTEXT = [
    ("AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY", "wJalrXUtnFEMI"),
    ("aws configure set aws_secret_access_key wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY", "wJalr"),
    ("export GITHUB_TOKEN=hunter2hunter2", "hunter2"),
    ("DATABASE_PASSWORD='correct horse'", "correct"),
    ('{"client_secret": "s3cr3t-v4lue"}', "s3cr3t"),
    ("mysql --password=Tr0ub4dor --user root", "Tr0ub4dor"),
    ("deploy --token zxcvbnmasdf", "zxcvbnmasdf"),
    ("psql postgres://app:pa55word@db.example.com/prod", "pa55word"),
    ("curl -H 'Authorization: Bearer abcdefghijklmnop1234' https://x", "abcdefghijklmnop1234"),
    ("AccountKey=" + MIXED * 2 + "==;EndpointSuffix=core.windows.net", MIXED),
]
NEAR_MISSES = [
    "git checkout 3f44650f22cc16f1ab740b149c477c714e53398a",
    "sha256:9b2a8c5e1f3d7a6b4c0e2f8d9a1b3c5e7f9d0a2b4c6e8f1a3b5d7e9f0a2c4e6b8",
    "550e8400-e29b-41d4-a716-446655440000",
    "/private/var/folders/x7/k2j3l4m5n6p7q8r9s0t1u2v3w4/T/earwarden-test-Ab3dE5gH/notes.md",
    "claude --max_tokens=1000",
    "tokens: 1000",
    "git commit --author='rehaan <r@example.com>'",
    "passwordless login works",
    "secret santa list",
    "export PATH=/usr/local/bin:$PATH",
    "pip install sphinx-autodoc-typehints",
    "uv run pytest -k test_token_refresh",
]


@pytest.mark.parametrize("secret", SECRETS)
def test_no_key_is_spoken_or_logged(secret: str) -> None:
    command = f"some-tool --flag {secret} --verbose"
    for tool, tool_input in (
        ("Bash", {"command": command}),
        ("Write", {"file_path": "a.txt", "content": secret}),
    ):
        judgement = engine.judge(tool, tool_input, CWD)
        assert judgement.tier == 3, secret  # the floor: secrets
        said = narrate("api", CWD, tool, tool_input, judgement).text
        assert secret not in said
        assert secret not in redact.redact(json.dumps(tool_input))


@pytest.mark.parametrize(("text", "hidden"), IN_CONTEXT)
def test_secrets_shown_by_their_context_are_hidden(text: str, hidden: str) -> None:
    assert hidden not in redact.redact(text), redact.redact(text)
    assert hidden not in narrate("api", CWD, "Bash", {"command": text}).text


@pytest.mark.parametrize("text", NEAR_MISSES)
def test_near_misses_stay_readable(text: str) -> None:
    assert redact.redact(text) == text
