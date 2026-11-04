"""The voice decider: speak a request, listen for the answer, and decide (Phase 1, milestone 6).

It plugs into the daemon in place of the hand-off decider. It only asks by voice when you're away
from the keyboard (or voice is pinned on) and the headset is the output; otherwise the request goes
straight to the screen. Under the safety stub (D-019) it only listens for requests voice may
approve; for the rest it says what's waiting and that it's on the screen.

One approval is asked at a time. If nothing is heard, it waits and asks again instead of handing
off (D-020); an answer it can't understand twice goes to the screen.
"""

from __future__ import annotations

import asyncio
import time
from typing import NamedTuple, Protocol

from earshot import contracts, stub, wire
from earshot.daemon.state import Pending
from earshot.narrator.spoken import speakable
from earshot.narrator.templates import narrate
from earshot.voice import intents


class Heard(NamedTuple):
    transcript: str
    recognizer: str  # "parakeet", or "parakeet+whisper" after a second listen (D-017)
    ms: int


class Voice(Protocol):
    def headset_ready(self) -> bool: ...
    def can_say(self, word: str) -> bool: ...
    async def say(self, text: str, chime: int | None = None) -> None: ...
    async def listen(self, seconds: float) -> Heard | None: ...
    async def open_mic(self) -> None: ...
    async def close_mic(self) -> None: ...


class Presence(Protocol):
    def away(self) -> bool: ...


def _decision(
    pending: Pending, outcome: contracts.Outcome, message: str | None = None
) -> contracts.Decision:
    if message is not None:
        message = message[: wire.MAX_DENY_MESSAGE_CHARS] or None
    return contracts.Decision(v=1, id=pending.request.id, outcome=outcome, message=message)


class VoiceDecider:
    def __init__(
        self,
        voice: Voice,
        presence: Presence,
        window_s: float = 8.0,
        reannounce_s: float = 60.0,
        reannounce_max: int = 3,
    ) -> None:
        self.voice = voice
        self.presence = presence
        self.window_s = window_s
        self.reannounce_s = reannounce_s
        self.reannounce_max = reannounce_max
        self._floor = asyncio.Lock()
        self._queued = 0

    async def __call__(self, pending: Pending) -> contracts.Decision:
        request = pending.request
        verdict = stub.judge(request.tool_name, request.tool_input, request.cwd)
        narration = narrate(
            pending.session.name, request.cwd, request.tool_name, request.tool_input
        )
        notes = pending.notes
        notes["tier"] = 1 if verdict.voice_ok and narration.fits else 3
        notes["rules"] = [f"stub: {verdict.reason}"]
        if not self.presence.away():
            notes["rules"].append("presence: at the keyboard")
            return _decision(pending, "handoff")
        if not self.voice.headset_ready():
            notes["rules"].append("presence: the headset isn't the output")
            return _decision(pending, "handoff")
        self._queued += 1  # one approval is asked at a time; the rest wait their turn
        try:
            await self._floor.acquire()
        finally:
            self._queued -= 1
        try:
            return await self._ask(pending, narration.text, verdict.voice_ok and narration.fits)
        finally:
            self._floor.release()

    async def _say(self, pending: Pending, text: str) -> None:
        said = speakable(text, self.voice.can_say)
        pending.notes["spoken"] = " ".join(filter(None, [pending.notes.get("spoken"), said]))
        start = time.monotonic()
        await self.voice.say(said, chime=pending.session.chime)
        timings = pending.notes.setdefault("timings_ms", {})
        timings["speak"] = timings.get("speak", 0) + int((time.monotonic() - start) * 1000)

    async def _ask(self, pending: Pending, text: str, listen: bool) -> contracts.Decision:
        if not listen:
            await self._say(pending, f"{text} It's on your screen.")
            return _decision(pending, "handoff")
        question = f"{text} Approve?"
        if self._queued:
            question += f" {self._queued} more waiting."
        await self.voice.open_mic()  # before speaking: the headset mode switch takes ~0.85 s (Q-2)
        try:
            await self._say(pending, question)
            silent = unclear = 0
            while True:
                heard = await self.voice.listen(self.window_s)
                if heard is None:
                    silent += 1
                    if silent > self.reannounce_max:
                        return _decision(pending, "handoff")
                    await self.voice.close_mic()
                    await asyncio.sleep(self.reannounce_s)  # hold, then ask again (D-020)
                    await self.voice.open_mic()
                    await self._say(pending, question)
                    continue
                pending.notes["transcript"] = heard.transcript
                pending.notes["recognizer"] = heard.recognizer
                pending.notes.setdefault("timings_ms", {})["recognize"] = heard.ms
                answer = intents.parse(heard.transcript)
                if answer.kind == "approve":
                    return _decision(pending, "allow")
                if answer.kind == "deny":
                    return _decision(pending, "deny")
                if answer.kind == "instruction":
                    return _decision(pending, "deny", answer.message)
                if answer.kind == "wait":
                    await self._say(pending, "Okay, it's on your screen.")
                    return _decision(pending, "handoff")
                unclear += 1
                if unclear >= 2:
                    await self._say(pending, "I didn't catch that. It's on your screen.")
                    return _decision(pending, "handoff")
                await self._say(pending, "Sorry, say yes or no.")
        finally:
            await self.voice.close_mic()
