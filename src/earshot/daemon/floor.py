"""The floor manager: one voice, a priority queue and three modes (Phase 4, milestone 2).

The spec's rules:

- One approval (P0) is open at a time; the rest queue, and Earshot says how many are waiting.
- An answer window is never interrupted: announcements wait for the floor, and never take it from
  an open approval. An approval takes the floor as soon as the current sentence ends.
- P1, failures: an approval that outlived its window ("docs approval moved to your screen").
- P2, a session finished, batched: finishes within 10 seconds merge ("api and docs finished").
- P3, progress, only inside briefings, never on its own.
- At most one unrequested announcement every 20 seconds. One that waited two minutes is dropped.
- Modes: quiet (approvals only), focus (approvals and failures; the default), and chatty
  (everything, with a briefing every five minutes while something is running).

Announcements obey presence routing like approvals do: at the keyboard, or without the headset,
nothing is said. No announcement can approve or deny a request; the floor only decides who speaks.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Literal, Protocol

log = logging.getLogger("earshot.floor")

Mode = Literal["quiet", "focus", "chatty"]
MODES: tuple[Mode, ...] = ("quiet", "focus", "chatty")
DEFAULT_MODE: Mode = "focus"

FAILURE, FINISHED, PROGRESS = 1, 2, 3  # P1, P2, P3; approvals are P0 and take the floor directly
GAP_S = 20.0  # between unrequested announcements
BATCH_S = 10.0  # finishes this close together are said as one
STALE_S = 120.0  # an announcement that waited this long is dropped
BRIEFING_EVERY_S = 300.0  # in chatty mode, while something is running
POLL_S = 0.5

# What each mode lets through, besides approvals.
ALLOWED: dict[Mode, frozenset[int]] = {
    "quiet": frozenset(),
    "focus": frozenset({FAILURE}),
    "chatty": frozenset({FAILURE, FINISHED, PROGRESS}),
}


class Speaker(Protocol):
    def headset_ready(self) -> bool: ...
    async def say(self, text: str, chime: int | None = None) -> None: ...


class Presence(Protocol):
    def away(self) -> bool: ...


@dataclass
class Announcement:
    priority: int
    text: str
    at: float  # when it was queued
    due: float  # the earliest it may be said (batching)
    names: list[str] = field(default_factory=list)  # a finish batch: who finished


class Turn:
    """One approval's hold on the floor. Between asks it can give the floor up for a while."""

    def __init__(self) -> None:
        self.held = False


def _join(names: list[str]) -> str:
    if len(names) <= 2:
        return " and ".join(names)
    return ", ".join(names[:-1]) + f" and {names[-1]}"


class Floor:
    def __init__(
        self,
        voice: Speaker,
        presence: Presence,
        now: Callable[[], float] = time.monotonic,
        briefing: Callable[[], str | None] | None = None,
    ) -> None:
        self.voice = voice
        self.presence = presence
        self.now = now
        self.briefing = briefing  # the briefing text while something is running, else None
        self.mode: Mode = DEFAULT_MODE
        self.lock = asyncio.Lock()  # whoever holds it is speaking, or listening for an answer
        self.last_said: str | None = None  # for "repeat"
        self._queued = 0  # approvals waiting for the floor
        self._waiting: list[Announcement] = []
        self._last_unrequested = -GAP_S
        self._last_briefing = 0.0
        self._task: asyncio.Task[None] | None = None

    # Approvals

    @property
    def queued(self) -> int:
        """How many approvals are waiting for the floor, besides the one being asked."""
        return self._queued

    @contextlib.asynccontextmanager
    async def approval(self) -> AsyncIterator[Turn]:
        """Take the floor for one approval. Spoken next, once the current sentence ends."""
        turn = Turn()
        await self._take(turn)
        try:
            yield turn
        finally:
            if turn.held:
                turn.held = False
                self.lock.release()

    @contextlib.asynccontextmanager
    async def released(self, turn: Turn) -> AsyncIterator[None]:
        """Give the floor up inside an approval while it waits to ask again (D-020's hold), and
        take it back after, in turn. Meanwhile push-to-talk works ("details" spells out this
        request), and another approval or an announcement can be said. If the request is
        answered meanwhile, the floor isn't taken back."""
        if turn.held:
            turn.held = False
            self.lock.release()
        yield
        await self._take(turn)

    async def _take(self, turn: Turn) -> None:
        self._queued += 1
        try:
            await self.lock.acquire()
        finally:
            self._queued -= 1
        turn.held = True

    # Announcements

    def announce(self, priority: int, text: str) -> None:
        """Queue an unrequested announcement. It's said when the floor is free and the mode
        allows, and dropped if that takes too long."""
        now = self.now()
        self._waiting.append(Announcement(priority, text, now, now))

    def finished(self, name: str) -> None:
        """A session finished. Finishes within 10 seconds are said together."""
        now = self.now()
        for item in self._waiting:
            if item.priority == FINISHED and now - item.at <= BATCH_S:
                if name not in item.names:
                    item.names.append(name)
                    item.text = f"{_join(item.names)} finished."
                return
        self._waiting.append(
            Announcement(FINISHED, f"{name} finished.", now, now + BATCH_S, [name])
        )

    async def say(self, text: str) -> bool:
        """Requested speech, such as a briefing you asked for: it waits for the floor, and the
        20-second gap doesn't apply. False if you're at the keyboard or the headset is away."""
        if not self._can_speak():
            return False
        async with self.lock:
            await self.voice.say(text)
            self.last_said = text
        return True

    def _can_speak(self) -> bool:
        return self.presence.away() and self.voice.headset_ready()

    def _next(self, now: float) -> Announcement | None:
        allowed = ALLOWED[self.mode]
        due = [a for a in self._waiting if a.due <= now and a.priority in allowed]
        return min(due, key=lambda a: (a.priority, a.at), default=None)

    def _drop_stale(self, now: float) -> None:
        kept = []
        for item in self._waiting:
            if now - item.at > STALE_S or item.priority not in ALLOWED[self.mode]:
                log.info("dropped an announcement: %s", item.text)
            else:
                kept.append(item)
        self._waiting = kept

    def _maybe_queue_briefing(self, now: float) -> None:
        if self.mode != "chatty" or self.briefing is None:
            return
        if now - self._last_briefing < BRIEFING_EVERY_S:
            return
        if any(a.priority == PROGRESS for a in self._waiting):
            return
        self._last_briefing = now
        text = self.briefing()
        if text:
            self._waiting.append(Announcement(PROGRESS, text, now, now))

    async def pump(self) -> bool:
        """Say the next announcement that's due, if the floor is free. True if one was said."""
        now = self.now()
        self._drop_stale(now)
        self._maybe_queue_briefing(now)
        if self.lock.locked() or now - self._last_unrequested < GAP_S:
            return False  # never interrupt an approval; keep the gap
        item = self._next(now)
        if item is None:
            return False
        self._waiting.remove(item)
        if not self._can_speak():
            log.info("not announced, at the keyboard or without the headset: %s", item.text)
            return False
        async with self.lock:
            await self.voice.say(item.text)
            self.last_said = item.text
            self._last_unrequested = self.now()
        return True

    # The background task

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.ensure_future(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run(self) -> None:
        while True:
            try:
                await self.pump()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("an announcement failed")
            await asyncio.sleep(POLL_S)
