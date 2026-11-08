"""Nods and shakes (Phase 2, milestone 7; D-018), on synthetic 50 Hz head motion."""

from __future__ import annotations

import math

from earshot.voice.gestures import Sample, detect

RATE = 50


def still(start: float, seconds: float, wobble: float = 0.05) -> list[Sample]:
    return [
        Sample(start + i / RATE, wobble * math.sin(i), wobble, -wobble)
        for i in range(int(seconds * RATE))
    ]


def swing(start: float, axis: str, peak: float = 1.6, seconds: float = 0.5) -> list[Sample]:
    """One down-and-up (or left-and-right) movement: a positive then a negative swing."""
    out = []
    for i in range(int(seconds * RATE)):
        value = peak * math.sin(2 * math.pi * i / (seconds * RATE))
        rates = {"x": 0.05, "y": 0.05, "z": 0.05, axis: value}
        out.append(Sample(start + i / RATE, rates["x"], rates["y"], rates["z"]))
    return out


def test_stillness_is_no_gesture() -> None:
    assert detect(still(0, 6), nods=True) is None


def test_a_shake_hands_off() -> None:
    assert detect([*still(0, 1), *swing(1.0, "z"), *still(1.5, 2)]) == "shake"


def test_nods_are_off_unless_switched_on() -> None:
    motion = [*still(0, 1.5), *swing(1.5, "x"), *swing(2.1, "x"), *still(2.6, 1)]
    assert detect(motion) is None
    assert detect(motion, nods=True) == "nod"


def test_a_single_nod_isnt_enough() -> None:
    assert detect([*still(0, 1.5), *swing(1.5, "x"), *still(2.0, 3)], nods=True) is None


def test_a_nod_needs_stillness_first() -> None:
    busy = [Sample(i / RATE, 0.6, 0.6, 0.6) for i in range(75)]  # walking, talking
    motion = [*busy, *swing(1.5, "x"), *swing(2.1, "x"), *still(2.6, 1)]
    assert detect(motion, nods=True) is None


def test_a_diagonal_movement_isnt_a_nod() -> None:
    def diagonal(yaw: float) -> list[Sample]:
        moves = [*swing(1.5, "x"), *swing(2.1, "x")]
        return [*still(0, 1.5), *(s._replace(z=s.x * yaw) for s in moves), *still(2.6, 1)]

    assert detect(diagonal(0.8), nods=True) == "shake"  # yaw past the threshold: to the screen
    assert detect(diagonal(0.6), nods=True) is None  # pitch doesn't dominate: no nod


def test_nods_too_far_apart_dont_count() -> None:
    motion = [*still(0, 1.5), *swing(1.5, "x"), *still(2.0, 3), *swing(5.0, "x")]
    assert detect(motion, nods=True) is None
