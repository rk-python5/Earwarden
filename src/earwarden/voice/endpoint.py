"""Endpointing: find one reply in the mic's frame levels, and whether it began too early (P-20).

Pure Python, so it's tested anywhere; `mac.py` feeds it the RMS level of each 20 ms frame.

- A reply is speech louder than the room: four times the quietest frame in the window, and at
  least 0.01. It ends after 400 ms of quiet or at 6 s (D-023).
- Only frames inside the window count as the reply (D-015). Frames from just before the window
  are looked at for one thing: if any was loud within 400 ms of the reply's start, the reply
  began before the window opened, after a barge-in or over the prompt's end. Its tail must never
  be parsed: "don't do it" cut short is "do it" (P-20).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import NamedTuple

END_SILENCE_S = 0.4
MAX_SPEECH_S = 6.0
LEAD_QUIET_S = END_SILENCE_S  # a pause too short to end a reply can't start one either
NOISE_FACTOR = 4
MIN_THRESHOLD = 0.01
MIN_NOISE = 0.001


class Reply(NamedTuple):
    start: float
    end: float | None  # None while the reply is still going
    cut_off: bool  # it began before the window opened (P-20)
    noise: float
    threshold: float
    loudest: float


def find_reply(
    levels: Sequence[tuple[float, float]],
    opened: float,
    now: float,
    window: float | None = None,
) -> Reply | None:
    """The first reply from `opened` on, or None if nobody has spoken yet.

    `levels` holds a (time, RMS) pair per frame, oldest first, and may begin before `opened`.
    `window` is when the window really opened, if the search starts later, after a noise that
    wasn't speech: only sound from before `window` makes a reply cut off. Without it, the
    ignored noise's own tail counted as "before the window".
    """
    inside = [(t, level) for t, level in levels if t >= opened]
    if not inside:
        return None
    noise = max(min(level for _, level in inside), MIN_NOISE)
    threshold = max(noise * NOISE_FACTOR, MIN_THRESHOLD)
    loud = [t for t, level in inside if level > threshold]
    if not loud:
        return None
    start = end = loud[0]
    for t in loud:
        if t - end >= END_SILENCE_S or t - start >= MAX_SPEECH_S:
            break
        end = t
    before = opened if window is None else window
    cut_off = any(level > threshold for t, level in levels if start - LEAD_QUIET_S <= t < before)
    loudest = max(level for t, level in inside if start <= t <= end)
    still_going = now - end < END_SILENCE_S and now - start < MAX_SPEECH_S
    return Reply(start, None if still_going else end, cut_off, noise, threshold, loudest)
