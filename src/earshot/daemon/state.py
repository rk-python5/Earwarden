"""What the daemon keeps track of: open sessions, and the requests waiting for an answer."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from earshot import contracts

CHIMES = 8  # each session gets one of 8 distinct chimes


def spoken_name(cwd: str | None) -> str:
    """A session is named after its folder ("api", "docs")."""
    name = PurePosixPath(cwd).name if cwd else ""
    return name or "a session"


@dataclass
class Session:
    session_id: str
    cwd: str | None
    name: str
    chime: int
    model: str | None = None
    started_at: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    last_message: str | None = None
    config_edited: bool = False  # build or test config changed: later commands rise (P-01)


class Sessions:
    def __init__(self) -> None:
        self._by_id: dict[str, Session] = {}

    def __len__(self) -> int:
        return len(self._by_id)

    def get(self, session_id: str) -> Session | None:
        return self._by_id.get(session_id)

    def all(self) -> list[Session]:
        return list(self._by_id.values())

    def seen(self, session_id: str, cwd: str | None) -> Session:
        """The session, registered on first sight: by SessionStart, or by any request or event
        from a session Earshot hasn't met, such as one started before the daemon (D-020)."""
        session = self._by_id.get(session_id)
        if session is None:
            session = Session(session_id, cwd, spoken_name(cwd), self._free_chime())
            self._by_id[session_id] = session
        else:
            session.last_seen = time.time()
            if session.cwd is None and cwd:
                session.cwd, session.name = cwd, spoken_name(cwd)
        return session

    def end(self, session_id: str) -> Session | None:
        return self._by_id.pop(session_id, None)

    def _free_chime(self) -> int:
        taken = {session.chime for session in self._by_id.values()}
        free = [chime for chime in range(CHIMES) if chime not in taken]
        return free[0] if free else len(self._by_id) % CHIMES


@dataclass
class Pending:
    """A PermissionRequest whose hook is waiting for an answer."""

    request: contracts.ApprovalRequest
    input_sha256: str
    session: Session
    received: float = field(default_factory=time.monotonic)
    cancel_reason: str | None = None
    cancelled: asyncio.Event = field(default_factory=asyncio.Event)
    # What the decider did, for the audit log: tier, rules, spoken, transcript, timings_ms...
    notes: dict[str, Any] = field(default_factory=dict)

    def cancel(self, reason: str) -> None:
        """Answered elsewhere, or no longer answerable: stop asking, and hand off."""
        if not self.cancelled.is_set():
            self.cancel_reason = reason
            self.cancelled.set()


class PendingRequests:
    def __init__(self) -> None:
        self._by_id: dict[str, Pending] = {}

    def __len__(self) -> int:
        return len(self._by_id)

    def add(self, pending: Pending) -> None:
        self._by_id[pending.request.id] = pending

    def remove(self, request_id: str) -> None:
        self._by_id.pop(request_id, None)

    def all(self) -> list[Pending]:
        return list(self._by_id.values())

    def for_session(self, session_id: str) -> list[Pending]:
        return [p for p in self._by_id.values() if p.request.session_id == session_id]

    def answered_by(self, event: contracts.Event) -> Pending | None:
        """The waiting request a PostToolUse belongs to: the tool ran, so you approved it on
        screen (D-020). It must match on session, tool and input, and on prompt when both
        carry one. If several match, the oldest is the one Claude Code asked first."""
        if event.event != "PostToolUse":
            return None
        matches = [
            p
            for p in self._by_id.values()
            if p.request.session_id == event.session_id
            and p.request.tool_name == event.tool_name
            and p.input_sha256 == event.input_sha256
            and (
                event.prompt_id is None
                or p.request.prompt_id is None
                or p.request.prompt_id == event.prompt_id
            )
            and not p.cancelled.is_set()
        ]
        return min(matches, key=lambda p: p.received, default=None)


@dataclass(frozen=True)
class Resolved:
    """How a request ended, for tests and, later, `earshot status` and the audit log."""

    request_id: str
    session_id: str
    tool_name: str
    outcome: str  # allow, deny, handoff, or cancelled when the hook was gone
    reason: str  # decided, tool_ran, hook_closed, session_ended, timeout, error, shutdown
    seconds: float
