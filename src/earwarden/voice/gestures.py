"""Nods and shakes from AirPods head motion (Phase 2, milestone 7; D-018, the spec's tier 1).

The helper (`earwarden-motion`) streams the head's rotation rate, in rad/s, from Core Motion. Only
motion inside an answer window counts, which removes most false nods before anything else.

- **A shake hands the request to the screen**, and never denies on its own (D-018): a false shake
  costs nothing. It's the plan's v1 pattern on the yaw axis: two opposite swings past 1 rad/s
  within 1.2 s.
- **A nod never approves on its own** in v1.0 (D-018). Nods are off unless switched on, and then
  need a stricter pattern than the plan's v1, which counted 49 false nods an hour on rehaan's
  AirPods 4:
  - two nods within 2 s, each two opposite pitch swings past 1 rad/s within 1.2 s
  - pitch clearly dominating: at each swing, at least twice the yaw and roll rates
  - about a second of stillness first, so talking or walking doesn't run into a nod

Axes, from Step 0's calibration: pitch (nodding) is x, yaw (shaking) is z.
"""

from __future__ import annotations

import itertools
from collections.abc import Iterable
from typing import Literal, NamedTuple

THRESHOLD = 1.0  # rad/s
SWING_WINDOW_S = 1.2
DOUBLE_NOD_S = 2.0
DOMINANCE = 2.0
STILL_S = 1.0
STILL_RATE = 0.3  # rad/s: under this on every axis counts as still

Gesture = Literal["nod", "shake"]


class Sample(NamedTuple):
    t: float  # seconds, monotonic
    x: float  # pitch rate
    y: float  # roll rate
    z: float  # yaw rate


def _swings(samples: list[Sample], axis: str, others: tuple[str, ...]) -> list[tuple[float, int]]:
    """(time, sign) of each swing past the threshold on `axis`, counted once, with hysteresis."""
    swings: list[tuple[float, int]] = []
    armed = True
    for s in samples:
        value = getattr(s, axis)
        if abs(value) < THRESHOLD / 2:
            armed = True
            continue
        if not armed or abs(value) < THRESHOLD:
            continue
        if others and any(abs(getattr(s, o)) * DOMINANCE > abs(value) for o in others):
            continue  # the other axes moved too much: not a clean swing on this one
        armed = False
        swings.append((s.t, 1 if value > 0 else -1))
    return swings


def _pairs(swings: list[tuple[float, int]]) -> list[tuple[float, float]]:
    """(start, end) of each pair of opposite swings within the window: one gesture each."""
    done: list[tuple[float, float]] = []
    previous: tuple[float, int] | None = None
    for t, sign in swings:
        if previous is not None and previous[1] != sign and t - previous[0] <= SWING_WINDOW_S:
            done.append((previous[0], t))
            previous = None
        else:
            previous = (t, sign)
    return done


def _still_before(samples: list[Sample], t: float) -> bool:
    """Whether the head was still for about a second before `t` (the gesture's first swing)."""
    before = [s for s in samples if t - STILL_S <= s.t < t - 0.15]  # not its own wind-up
    return bool(before) and all(max(abs(s.x), abs(s.y), abs(s.z)) < STILL_RATE for s in before)


def detect(samples: Iterable[Sample], nods: bool = False) -> Gesture | None:
    """The gesture in an answer window's motion, if any. A shake wins over a nod."""
    ordered = sorted(samples)
    if _pairs(_swings(ordered, "z", ())):
        return "shake"
    if not nods:
        return None
    found = _pairs(_swings(ordered, "x", ("y", "z")))
    for (start, _), (_, end) in itertools.pairwise(found):
        if end - start <= DOUBLE_NOD_S + SWING_WINDOW_S and _still_before(ordered, start):
            return "nod"
    return None
