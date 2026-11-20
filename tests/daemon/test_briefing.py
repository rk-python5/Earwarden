"""Session activity and the spoken briefing (Phase 4, milestone 1)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from earwarden import contracts, paths, wire
from earwarden.daemon import briefing
from earwarden.daemon.server import Daemon
from earwarden.daemon.state import Session, Sessions

NOW = 1_000_000.0


def session(name: str = "api", **changes: Any) -> Session:
    made = Session(f"id-{name}-{len(changes)}", f"/code/{name}", name, 0, started_at=NOW - 5000)
    for key, value in changes.items():
        setattr(made, key, value)
    made.last_seen = changes.get("last_seen", NOW)
    return made


def test_durations_round_down_and_say_plainly() -> None:
    assert briefing.duration(0) == "under a minute"
    assert briefing.duration(59) == "under a minute"
    assert briefing.duration(60) == "1 minute"
    assert briefing.duration(12 * 60 + 40) == "12 minutes"
    assert briefing.duration(3600) == "1 hour"
    assert briefing.duration(2.5 * 3600) == "2 hours"
    assert briefing.duration(-5) == "under a minute"


def test_each_state_in_a_few_words() -> None:
    working = session(working_since=NOW - 12 * 60, tools_run=14)
    assert briefing.status(working, False, NOW) == "running 12 minutes, 14 tools run"
    assert briefing.status(session(working_since=NOW - 60, tools_run=1), False, NOW).endswith(
        "1 tool run"
    )
    assert briefing.status(working, True, NOW) == "waiting for you"
    assert briefing.status(session(finished_at=NOW - 300), False, NOW) == "finished 5 minutes ago"
    assert briefing.status(session(idle=True), False, NOW) == "idle"
    assert briefing.status(session(), False, NOW) == "just started"


def test_a_running_session_gone_silent_is_called_quiet() -> None:
    # Esc stops the agent without a Stop event, so "running" can't be trusted forever.
    stale = session(working_since=NOW - 3600, tools_run=40, last_seen=NOW - 20 * 60)
    assert briefing.status(stale, False, NOW) == "quiet for 20 minutes"


def test_the_briefing_puts_what_needs_you_first() -> None:
    sessions = [
        session("deploy", finished_at=NOW - 300),
        session("docs"),
        session("api", working_since=NOW - 720, tools_run=14),
    ]
    waiting = {sessions[1].session_id}
    assert briefing.briefing(sessions, waiting, NOW) == (
        "Three sessions. docs: waiting for you. api: running 12 minutes, 14 tools run. "
        "deploy: finished 5 minutes ago."
    )


def test_no_sessions_and_one_session() -> None:
    assert briefing.briefing([], set(), NOW) == "No sessions are open."
    assert briefing.briefing([session("api", idle=True)], set(), NOW) == "One session. api: idle."


def test_two_sessions_with_one_name_are_told_apart() -> None:
    first, second = session("api"), session("api", idle=True)
    spoken = briefing.names([first, second])
    assert spoken[first.session_id] == "api"
    assert spoken[second.session_id] == "api second"


def test_a_long_list_is_cut_short_and_stays_brief() -> None:
    sessions = [
        session(f"s{n}", working_since=NOW - 3 * 3600, tools_run=999, last_seen=NOW)
        for n in range(8)
    ]
    for n, one in enumerate(sessions):
        one.session_id = f"id-{n}"
    text = briefing.briefing(sessions, set(), NOW)
    assert text.startswith("Eight sessions.")
    assert text.endswith("And three more.")
    assert len(text.split()) <= 50  # about 15 seconds at Kokoro's pace


def event(name: str, **fields: Any) -> contracts.Event:
    body: dict[str, Any] = {
        "v": 1,
        "token": "ab" * 32,
        "source": "claude_code",
        "event": name,
        "session_id": "s1",
        "cwd": "/Users/rehaan/code/api",
        **fields,
    }
    return contracts.Event.model_validate_json(wire.encode(body))


def tool_ran() -> contracts.Event:
    return event("PostToolUse", tool_name="Bash", input_sha256=wire.input_sha256({"command": "ls"}))


def test_events_tell_the_daemon_what_a_session_is_doing(tmp_path: Path) -> None:
    daemon = Daemon(paths.resolve(str(tmp_path)))
    daemon._on_event(event("SessionStart", model="opus"))
    (one,) = daemon.sessions.all()
    assert one.working_since is None
    daemon._on_event(tool_ran())
    daemon._on_event(tool_ran())
    assert one.working_since is not None
    assert one.tools_run == 2
    daemon._on_event(event("Stop", last_assistant_message="All done."))
    assert one.working_since is None
    assert one.finished_at is not None
    assert one.last_message == "All done."
    daemon._on_event(event("Notification", notification_type="idle_prompt"))
    assert one.idle
    daemon._on_event(tool_ran())  # a new run starts: not idle, tools counted afresh
    assert (one.idle, one.tools_run, one.finished_at) == (False, 1, None)


def test_an_idle_notice_doesnt_end_a_run(tmp_path: Path) -> None:
    daemon = Daemon(paths.resolve(str(tmp_path)))
    daemon._on_event(tool_ran())
    daemon._on_event(event("Notification", notification_type="idle_prompt"))
    (one,) = daemon.sessions.all()
    assert one.working_since is not None
    assert not one.idle


@pytest.mark.parametrize("n", [1, 2, 9])
def test_chimes_stay_distinct_for_up_to_eight_sessions(n: int) -> None:
    sessions = Sessions()
    made = [sessions.seen(f"s{i}", f"/code/p{i}") for i in range(n)]
    chimes = [m.chime for m in made]
    assert len(set(chimes)) == min(n, 8)
