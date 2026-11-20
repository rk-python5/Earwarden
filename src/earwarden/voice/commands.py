"""What a push-to-talk command means, by rules only (Phase 4, milestone 3).

The v1.0 commands are the spec's: status, repeat, details, stop, and the three mode names. A
command window never parses yes or no: nothing said here approves or denies a request. Anything
that isn't a known command is "unclear", and Earwarden says it didn't catch that.
"""

from __future__ import annotations

from typing import Literal, NamedTuple

from earwarden.voice.intents import normalize

Kind = Literal["status", "repeat", "details", "stop", "mode", "unclear"]

# Words that only carry the request along: "earwarden, quiet mode please".
FILLER = frozenset(
    {"earwarden", "ear", "warden", "please", "mode", "the", "a", "me", "now", "hey", "ok", "okay"}
)

PHRASES: dict[str, Kind] = {
    "status": "status",
    "briefing": "status",
    "what's everyone doing": "status",
    "whats everyone doing": "status",
    "what is everyone doing": "status",
    "what's going on": "status",
    "whats going on": "status",
    "what's happening": "status",
    "whats happening": "status",
    "repeat": "repeat",
    "again": "repeat",
    "say again": "repeat",
    "say that again": "repeat",
    "what": "repeat",
    "details": "details",
    "detail": "details",
    "spell it out": "details",
    "spell it": "details",
    "stop": "stop",
    "silence": "stop",
    "be quiet": "stop",
    "shut up": "stop",
    "enough": "stop",
}
MODES = ("quiet", "focus", "chatty")


class Command(NamedTuple):
    kind: Kind
    mode: str | None = None  # for "mode": quiet, focus or chatty


def parse(transcript: str) -> Command:
    words = [w for w in normalize(transcript).split() if w not in FILLER]
    phrase = " ".join(words)
    if phrase in MODES:
        return Command("mode", phrase)
    if phrase in PHRASES:
        return Command(PHRASES[phrase])
    return Command("unclear")
