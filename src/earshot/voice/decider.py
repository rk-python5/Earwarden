"""The voice decider: speak a request, listen for the answer, and decide (Phase 1, milestone 6).

It plugs into the daemon in place of the hand-off decider. It only asks by voice when you're away
from the keyboard (or voice is pinned on) and the headset is the output; otherwise the request goes
straight to the screen. The policy engine gives each request a tier. Voice listens only for the
tiers it may approve (tier 1, until challenge words and the voiceprint arrive); for the rest it
says what's waiting and that it's on the screen.

One approval is asked at a time. If nothing is heard, it waits and asks again instead of handing
off (D-020); an answer it can't understand twice goes to the screen. A tone marks when to answer,
and an answer begun before it is never parsed: Earshot asks you to wait for the tone (D-028).

Tier 2 asks for a fresh challenge word ("To install, say: approve harbor.", milestone 5), and
approves only when the word matches and the voiceprint says it's you (milestone 6). A plain "yes"
never answers a challenge. Until a voiceprint is enrolled, tier 2 goes to the screen.
"""

from __future__ import annotations

import asyncio
import time
from typing import Literal, NamedTuple, Protocol

from earshot import contracts, paths, wire
from earshot.daemon.floor import FAILURE, Floor
from earshot.daemon.state import Pending
from earshot.narrator.spoken import speakable
from earshot.narrator.templates import narrate
from earshot.policy import engine, risk
from earshot.voice import challenge, intents

CUT_OFF = "cut off"  # Heard.recognizer for a reply begun before the window: never parsed (P-20)
SHAKE, NOD = "shake", "nod"  # Heard.recognizer for a head gesture in the window (D-018)


class Speaker(NamedTuple):
    score: float  # the voiceprint's similarity to the enrolled profile
    verdict: Literal["match", "borderline", "mismatch"]


class Heard(NamedTuple):
    transcript: str
    recognizer: str  # "parakeet", "parakeet+whisper" after a second listen (D-017), or CUT_OFF
    ms: int
    speaker: Speaker | None = None  # the voiceprint's verdict, once one is enrolled


class Voice(Protocol):
    def headset_ready(self) -> bool: ...
    def speaker_ready(self) -> bool: ...  # a voiceprint is enrolled: tier 2 can be asked
    def can_say(self, word: str) -> bool: ...
    # With `tone`, the listening tone follows the last word at once: an answer comes next.
    async def say(self, text: str, chime: int | None = None, tone: bool = False) -> None: ...
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
        where: paths.Paths | None = None,
        floor: Floor | None = None,
        gate: risk.Gate | None = None,
    ) -> None:
        self.voice = voice
        self.where = where  # where the policy files are; None for the built-in rules alone
        self.presence = presence
        self.window_s = window_s
        self.reannounce_s = reannounce_s
        self.reannounce_max = reannounce_max
        # Who speaks when (Phase 4). The daemon shares its floor, so announcements wait for an
        # open answer window; on its own, the decider makes one.
        self.floor = floor if floor is not None else Floor(voice, presence)
        self.gate = gate  # the optional risk gate (Phase 4): it can only raise a tier

    async def __call__(self, pending: Pending) -> contracts.Decision:
        request = pending.request
        edited = pending.session.config_edited
        if self.where is None:
            judgement = engine.judge_built_in(request, edited)
        else:
            judgement = engine.judge_request(self.where, request, edited)
        judgement = risk.apply(
            self.gate, judgement, request.tool_name, request.tool_input, request.cwd
        )
        narration = narrate(
            pending.session.name, request.cwd, request.tool_name, request.tool_input, judgement
        )
        notes = pending.notes
        notes["tier"] = judgement.tier
        notes["rules"] = list(judgement.rules)
        notes["checker"] = "pass" if narration.fits else "fail"
        if not narration.fits:
            notes["rules"].append(narration.problem or "narrator: can't be said faithfully")
        word: str | None = None
        if judgement.tier == 2:
            if self.voice.speaker_ready():
                word = challenge.pick()
            else:
                notes["rules"].append("voice: tier 2 waits for an enrolled voiceprint")
        voice_ok = (judgement.tier in engine.VOICE_TIERS or word is not None) and narration.fits
        if not self.presence.away():
            notes["rules"].append("presence: at the keyboard")
            return _decision(pending, "handoff")
        if not self.voice.headset_ready():
            notes["rules"].append("presence: the headset isn't the output")
            return _decision(pending, "handoff")
        async with self.floor.approval():  # one at a time; the rest wait their turn
            return await self._ask(
                pending, narration.text, voice_ok, word, narration.verb, judgement.raised
            )

    async def _say(self, pending: Pending, text: str, tone: bool = False) -> None:
        said = speakable(text, self.voice.can_say)
        pending.notes["spoken"] = " ".join(filter(None, [pending.notes.get("spoken"), said]))
        start = time.monotonic()
        await self.voice.say(said, chime=pending.session.chime, tone=tone)
        self.floor.last_said = said
        timings = pending.notes.setdefault("timings_ms", {})
        timings["speak"] = timings.get("speak", 0) + int((time.monotonic() - start) * 1000)

    async def _ask(
        self,
        pending: Pending,
        text: str,
        listen: bool,
        word: str | None,
        verb: str,
        raised: str | None = None,
    ) -> contracts.Decision:
        if not listen:
            why = f" Raised, for {raised}." if raised else ""
            await self._say(pending, f"{text}{why} It's on your screen.")
            return _decision(pending, "handoff")
        answer_with = f"say: approve {word}" if word else "say yes or no"
        question = f"{text} To {verb}, {answer_with}." if word else f"{text} Approve?"
        if word:
            pending.notes["challenge"] = word
        if self.floor.queued:
            question += f" {self.floor.queued} more waiting."
        await self.voice.open_mic()  # before speaking: the headset mode switch takes ~0.85 s (Q-2)
        try:
            await self._say(pending, question, tone=True)
            silent = unclear = 0
            while True:
                heard = await self.voice.listen(self.window_s)
                if heard is None:
                    silent += 1
                    if silent > self.reannounce_max:
                        name = pending.session.name
                        self.floor.announce(FAILURE, f"{name} approval moved to your screen.")
                        return _decision(pending, "handoff")
                    await self.voice.close_mic()
                    await asyncio.sleep(self.reannounce_s)  # hold, then ask again (D-020)
                    await self.voice.open_mic()
                    await self._say(pending, question, tone=True)
                    continue
                pending.notes["transcript"] = heard.transcript
                pending.notes["recognizer"] = heard.recognizer
                pending.notes.setdefault("timings_ms", {})["recognize"] = heard.ms
                if heard.speaker is not None:
                    pending.notes["voiceprint"] = heard.speaker.score
                if heard.recognizer == SHAKE:  # never a deny on its own: to the screen (D-018)
                    pending.notes["gesture"] = SHAKE
                    await self._say(pending, "Okay, it's on your screen.")
                    return _decision(pending, "handoff")
                if heard.recognizer == NOD and word is None:  # tier 1 only, and only if switched on
                    pending.notes["gesture"] = NOD
                    return _decision(pending, "allow")
                if heard.recognizer == CUT_OFF:
                    answer = intents.Intent("unclear")  # begun before the tone: never parsed
                else:
                    answer = intents.parse(heard.transcript)
                if word is not None and heard.recognizer != CUT_OFF:
                    if challenge.matches(heard.transcript, word):
                        if heard.speaker is not None and heard.speaker.verdict == "match":
                            return _decision(pending, "allow")
                        verdict = heard.speaker.verdict if heard.speaker else "not checked"
                        pending.notes["rules"] = [
                            *pending.notes.get("rules", []),
                            f"voiceprint: {verdict}",
                        ]
                        await self._say(pending, "Didn't catch that clearly; it's on your screen.")
                        return _decision(pending, "handoff")
                    if answer.kind == "approve":
                        answer = intents.Intent("unclear")  # a plain yes never answers a challenge
                elif answer.kind == "approve":
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
                if heard.recognizer == CUT_OFF:
                    await self._say(pending, f"Wait for the tone, then {answer_with}.", tone=True)
                else:
                    await self._say(pending, f"Sorry, {answer_with}.", tone=True)
        finally:
            await self.voice.close_mic()
