"""The daemon's bookkeeping: session names and chimes, and which request a tool run answers."""

from __future__ import annotations

from typing import Any

from earwarden import contracts, wire
from earwarden.daemon.state import CHIMES, Pending, PendingRequests, Sessions, spoken_name

TOKEN = "ab" * 32


def request(**changes: Any) -> contracts.ApprovalRequest:
    fields: dict[str, Any] = {
        "v": 1,
        "id": wire.new_request_id(),
        "token": TOKEN,
        "source": "claude_code",
        "session_id": "s1",
        "prompt_id": "p1",
        "cwd": "/Users/rehaan/code/api",
        "permission_mode": "default",
        "tool_name": "Bash",
        "tool_input": {"command": "pytest"},
        "received_at": wire.utc_timestamp(),
    }
    fields.update(changes)
    return contracts.ApprovalRequest.model_validate_json(wire.encode(fields))


def tool_ran(**changes: Any) -> contracts.Event:
    fields: dict[str, Any] = {
        "v": 1,
        "token": TOKEN,
        "source": "claude_code",
        "event": "PostToolUse",
        "session_id": "s1",
        "prompt_id": "p1",
        "tool_name": "Bash",
        "input_sha256": wire.input_sha256({"command": "pytest"}),
    }
    fields.update(changes)
    return contracts.Event.model_validate_json(wire.encode(fields))


def waiting(sessions: Sessions, pending: PendingRequests, **changes: Any) -> Pending:
    req = request(**changes)
    item = Pending(req, wire.input_sha256(req.tool_input), sessions.seen(req.session_id, req.cwd))
    pending.add(item)
    return item


def test_sessions_are_named_after_their_folder() -> None:
    assert spoken_name("/Users/rehaan/code/api") == "api"
    assert spoken_name("/Users/rehaan/code/docs/") == "docs"
    assert spoken_name("/") == "a session"
    assert spoken_name(None) == "a session"


def test_each_session_gets_its_own_chime_and_freed_chimes_are_reused() -> None:
    sessions = Sessions()
    chimes = [sessions.seen(f"s{i}", f"/code/s{i}").chime for i in range(CHIMES)]
    assert sorted(chimes) == list(range(CHIMES))
    sessions.end("s3")
    assert sessions.seen("new", "/code/new").chime == 3


def test_a_session_first_seen_without_a_folder_gets_one_later() -> None:
    sessions = Sessions()
    sessions.seen("s1", None)
    assert sessions.seen("s1", "/code/api").name == "api"


def test_a_tool_run_answers_the_matching_request() -> None:
    sessions, pending = Sessions(), PendingRequests()
    item = waiting(sessions, pending)
    assert pending.answered_by(tool_ran()) is item


def test_a_tool_run_must_match_session_tool_input_and_prompt() -> None:
    sessions, pending = Sessions(), PendingRequests()
    waiting(sessions, pending)
    for different in (
        {"session_id": "s2"},
        {"tool_name": "Edit"},
        {"input_sha256": wire.input_sha256({"command": "pytest -x"})},
        {"prompt_id": "p2"},
    ):
        assert pending.answered_by(tool_ran(**different)) is None


def test_a_missing_prompt_id_doesnt_block_a_match() -> None:
    sessions, pending = Sessions(), PendingRequests()
    item = waiting(sessions, pending, prompt_id=None)
    assert pending.answered_by(tool_ran()) is item


def test_identical_requests_are_answered_oldest_first() -> None:
    sessions, pending = Sessions(), PendingRequests()
    first = waiting(sessions, pending)
    second = waiting(sessions, pending)
    assert pending.answered_by(tool_ran()) is first
    first.cancel("tool_ran")
    assert pending.answered_by(tool_ran()) is second


def test_only_post_tool_use_answers_a_request() -> None:
    sessions, pending = Sessions(), PendingRequests()
    waiting(sessions, pending)
    stop = contracts.Event(v=1, token=TOKEN, source="claude_code", event="Stop", session_id="s1")
    assert pending.answered_by(stop) is None


def test_a_cancellation_keeps_its_first_reason() -> None:
    sessions, pending = Sessions(), PendingRequests()
    item = waiting(sessions, pending)
    item.cancel("tool_ran")
    item.cancel("shutdown")
    assert item.cancel_reason == "tool_ran"
    assert item.cancelled.is_set()
