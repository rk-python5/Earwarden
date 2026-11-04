"""The five message contracts accept the spec's examples and refuse anything else."""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import ValidationError

from earshot import contracts, wire

TOKEN = "0123456789abcdef" * 4


def request(**changes: Any) -> dict[str, Any]:
    """The spec's ApprovalRequest example, with a real token."""
    message: dict[str, Any] = {
        "v": 1,
        "id": "req_01JD3KX9",
        "token": TOKEN,
        "source": "claude_code",
        "session_id": "8f1c2a",
        "cwd": "/Users/rehaan/code/api",
        "permission_mode": "default",
        "tool_name": "Bash",
        "tool_input": {"command": "git push origin feature/login"},
        "received_at": "2026-11-03T10:15:02.114Z",
    }
    message.update(changes)
    return message


def parse(model: type[contracts.Contract], message: dict[str, Any]) -> contracts.Contract:
    return model.model_validate_json(json.dumps(message))


def test_the_spec_examples_are_valid() -> None:
    parse(contracts.ApprovalRequest, request())
    parse(
        contracts.Assessment,
        {
            "tier": 2,
            "rules": ["push"],
            "critical": {"remote": "origin", "branch": "feature/login", "force": False},
            "gate": {"score": 0.31, "reasons": []},
            "voice_ok": True,
        },
    )
    parse(
        contracts.Decision,
        {
            "v": 1,
            "id": "req_01JD3KX9",
            "outcome": "deny",
            "message": "use poetry instead",
            "tier": 2,
        },
    )
    parse(
        contracts.Event,
        {
            "v": 1,
            "token": TOKEN,
            "source": "claude_code",
            "event": "Stop",
            "session_id": "8f1c2a",
            "cwd": "/Users/rehaan/code/api",
            "last_assistant_message": "Refactor done, 14 tests pass.",
        },
    )
    parse(
        contracts.AuditRecord,
        {
            "id": "req_01JD3KX9",
            "ts": "2026-11-03T10:15:09.802Z",
            "session": "api",
            "tool": "Bash",
            "input_sha256": "9b" * 32,
            "input_redacted": "git push origin feature/login",
            "tier": 2,
            "rules": ["push"],
            "spoken": "API wants to push feature slash login to origin. Say: approve orchard.",
            "checker": "pass",
            "transcript": "approve orchard",
            "recognizer": "parakeet",
            "challenge": "orchard",
            "voiceprint": 0.71,
            "gesture": None,
            "outcome": "allow",
            "timings_ms": {"policy": 4, "narrate": 2, "tts_first": 140, "asr": 160, "verify": 55},
            "prev_hash": "c4" * 32,
            "hash": "07" * 32,
        },
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"v": 2},
        {"v": True},
        {"v": 1.0},
        {"id": "01JD3KX9"},
        {"token": "secret"},
        {"source": "cursor"},
        {"cwd": "code/api"},
        {"session_id": ""},
        {"tool_input": ["git", "push"]},
        {"received_at": "yesterday"},
        {"approved": True},
    ],
)
def test_a_bad_request_is_refused(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        parse(contracts.ApprovalRequest, request(**changes))


def test_a_request_must_carry_its_version() -> None:
    message = request()
    del message["v"]
    with pytest.raises(ValidationError):
        parse(contracts.ApprovalRequest, message)


@pytest.mark.parametrize(
    "decision",
    [
        {"v": 1, "id": "req_01JD3KX9", "outcome": "allow", "message": "sure"},
        {"v": 1, "id": "req_01JD3KX9", "outcome": "handoff", "message": "later"},
        {"v": 1, "id": "req_01JD3KX9", "outcome": "maybe"},
        {"v": 1, "id": "req_01JD3KX9", "outcome": "deny", "message": ""},
        {"v": 1, "id": "req_01JD3KX9", "outcome": "allow", "tier": 4},
        {"v": 1, "id": "req_01JD3KX9", "outcome": "allow", "tier": "1"},
        {"v": 1, "id": "req_01JD3KX9", "outcome": "allow", "tier": True},
    ],
)
def test_a_bad_decision_is_refused(decision: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        parse(contracts.Decision, decision)


def test_a_deny_message_has_a_length_limit() -> None:
    message = "x" * (wire.MAX_DENY_MESSAGE_CHARS + 1)
    with pytest.raises(ValidationError):
        parse(
            contracts.Decision,
            {"v": 1, "id": "req_01JD3KX9", "outcome": "deny", "message": message},
        )


def test_a_post_tool_use_event_names_its_tool() -> None:
    event = {
        "v": 1,
        "token": TOKEN,
        "source": "claude_code",
        "event": "PostToolUse",
        "session_id": "s",
    }
    with pytest.raises(ValidationError):
        parse(contracts.Event, event)
    parse(contracts.Event, {**event, "tool_name": "Bash", "input_sha256": "ab" * 32})


def test_contracts_are_frozen() -> None:
    decision = contracts.Decision(v=1, id="req_01JD3KX9", outcome="allow")
    with pytest.raises(ValidationError):
        decision.outcome = "deny"  # type: ignore[misc]


def test_the_ids_the_wire_makes_fit_the_contract() -> None:
    parse(
        contracts.ApprovalRequest,
        request(id=wire.new_request_id(), received_at=wire.utc_timestamp()),
    )
