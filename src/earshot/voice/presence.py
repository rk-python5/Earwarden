"""Presence routing: use voice only when you're away from the keyboard (macOS).

macOS keeps the time since the last keyboard or mouse input as `HIDIdleTime` in the IOKit
registry, in nanoseconds. Reading it through `ioreg` takes a few milliseconds and needs no
permission. If it can't be read, Earshot assumes you're at the keyboard and stays quiet.
"""

from __future__ import annotations

import re
import subprocess

IOREG = "/usr/sbin/ioreg"


def idle_seconds() -> float | None:
    try:
        out = subprocess.run(  # noqa: S603 - a fixed system tool and fixed arguments
            [IOREG, "-c", "IOHIDSystem", "-d", "4"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r'"HIDIdleTime"\s*=\s*(\d+)', out)
    return int(match.group(1)) / 1e9 if match else None


class KeyboardPresence:
    def __init__(self, away_after_s: float = 45.0, pinned: bool = False) -> None:
        self.away_after_s = away_after_s
        self.pinned = pinned  # voice even at the keyboard, for testing and by choice

    def away(self) -> bool:
        if self.pinned:
            return True
        idle = idle_seconds()
        return idle is not None and idle >= self.away_after_s
