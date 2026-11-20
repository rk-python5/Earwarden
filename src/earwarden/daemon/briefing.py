""" "What's everyone doing?": a spoken summary of the open sessions (Phase 4, milestone 1).

Built from the session registry alone: names, how long each has been running, how many tools it
has run, and whether it's waiting for you. No file contents and no messages are read aloud. It
stays under about 15 seconds of speech: five sessions at most, then "and N more".
"""

from __future__ import annotations

import time

from earwarden.daemon.state import Session

MAX_NAMED = 5
QUIET_AFTER_S = 300.0  # a "running" session silent this long may have been interrupted with Esc
_NUMBERS = (
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
)  # fmt: skip
_ORDINALS = ("second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth")


def count(n: int) -> str:
    return _NUMBERS[n] if n < len(_NUMBERS) else str(n)


def duration(seconds: float) -> str:
    """ "under a minute", "12 minutes", "2 hours": rounded down, since it's only a feel."""
    minutes = int(max(seconds, 0) // 60)
    if minutes < 1:
        return "under a minute"
    if minutes < 60:
        return f"{minutes} minute" + ("" if minutes == 1 else "s")
    hours = minutes // 60
    return f"{hours} hour" + ("" if hours == 1 else "s")


def status(session: Session, waiting: bool, now: float) -> str:
    """What one session is doing, in a few words."""
    if waiting:
        return "waiting for you"
    if session.working_since is not None:
        if now - session.last_seen > QUIET_AFTER_S:
            return f"quiet for {duration(now - session.last_seen)}"
        tools = f"{session.tools_run} tool" + ("" if session.tools_run == 1 else "s")
        return f"running {duration(now - session.working_since)}, {tools} run"
    if session.finished_at is not None:
        return f"finished {duration(now - session.finished_at)} ago"
    return "idle" if session.idle else "just started"


def names(sessions: list[Session]) -> dict[str, str]:
    """Spoken names, with a second "api" told apart as "api second"."""
    seen: dict[str, int] = {}
    spoken: dict[str, str] = {}
    for session in sessions:
        n = seen.get(session.name, 0)
        seen[session.name] = n + 1
        spoken[session.session_id] = (
            session.name if n == 0 else f"{session.name} {_ORDINALS[min(n - 1, 8)]}"
        )
    return spoken


def _order(session: Session, waiting: set[str]) -> tuple[int, float]:
    if session.session_id in waiting:
        return 0, session.started_at
    if session.working_since is not None:
        return 1, session.started_at
    if session.finished_at is not None:
        return 2, -session.finished_at  # the newest finish first
    return 3, session.started_at


def briefing(sessions: list[Session], waiting: set[str], now: float | None = None) -> str:
    """The briefing: waiting sessions first, then running, finished and idle ones."""
    now = time.time() if now is None else now
    if not sessions:
        return "No sessions are open."
    spoken = names(sessions)
    ordered = sorted(sessions, key=lambda s: _order(s, waiting))
    word = "session" if len(sessions) == 1 else "sessions"
    parts = [f"{count(len(sessions)).capitalize()} {word}."]
    for session in ordered[:MAX_NAMED]:
        line = status(session, session.session_id in waiting, now)
        parts.append(f"{spoken[session.session_id]}: {line}.")
    if len(ordered) > MAX_NAMED:
        parts.append(f"And {count(len(ordered) - MAX_NAMED)} more.")
    return " ".join(parts)
