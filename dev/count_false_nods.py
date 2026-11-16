"""Count false nods during normal work (milestone 7's done-when; D-018). Run on the Mac:

    src/earshot/helper_app/build.sh
    uv run python dev/count_false_nods.py --minutes 60 [--home .tools/earshot]

Stop earshotd first: this takes the helper's place for the hour. It opens the helper app, asks it
for head motion only (never the mic), and you work as usual with the AirPods in, without nodding
on purpose. It cuts the motion into 6-second answer windows and reports:

- the strict double nod (D-018): windows with a false nod, per hour and as a share of windows.
  The target is under 1% of windows.
- the plan's v1 nod (one swing pair), for comparison with Step 0's 49 an hour
- shakes, which only hand a request to the screen, so they cost nothing
"""

from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
import tempfile
import time
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from earshot import auth, paths  # noqa: E402
from earshot.voice import gestures  # noqa: E402
from earshot.voice.helper import HelperLink  # noqa: E402

APP = ROOT / "helpers" / "earshot-motion" / ".build" / "EarshotMotion.app"
WINDOW_S = 6.0


async def record(minutes: float, where: paths.Paths) -> list[gestures.Sample]:
    folder = Path(tempfile.mkdtemp(prefix="nods-"))
    link = HelperLink(folder / "helper.sock", auth.ensure_token(where.token))
    await link.start()
    link.motion = deque(maxlen=None)  # keep the whole hour
    subprocess.run(  # noqa: S603 - the system's open, with our own app
        [
            "/usr/bin/open",
            "-g",
            "-a",
            str(APP),
            "--args",
            "--socket",
            str(link.socket_path),
            "--token-file",
            str(where.token),
        ],
        check=True,
    )
    for _ in range(100):
        if link.connected:
            break
        await asyncio.sleep(0.1)
    else:
        print("The helper didn't connect. Is it built, and are the AirPods connected?")
        return []
    link.want(motion=True)
    print(f"Recording head motion for {minutes:g} minutes. Work as usual; don't nod on purpose.")
    end = time.monotonic() + minutes * 60
    while time.monotonic() < end:
        await asyncio.sleep(10)
        print(
            f"  {len(link.motion):,} samples, {(end - time.monotonic()) / 60:.0f} min left",
            end="\r",
        )
    link.want(motion=False)
    await link.stop()
    return list(link.motion)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--minutes", type=float, default=60.0)
    parser.add_argument("--home", help="Earshot's home, for the token")
    args = parser.parse_args()
    samples = asyncio.run(record(args.minutes, paths.resolve(args.home)))
    if not samples:
        return 1
    start, stop = samples[0].t, samples[-1].t
    hours = (stop - start) / 3600
    windows = strict = shakes = v1 = 0
    t = start
    while t + WINDOW_S <= stop:
        window = [s for s in samples if t <= s.t < t + WINDOW_S]
        windows += 1
        found = gestures.detect(window, nods=True)
        strict += found == "nod"
        shakes += found == "shake"
        v1 += bool(gestures._pairs(gestures._swings(window, "x", ())))
        t += WINDOW_S
    rate = len(samples) / max(stop - start, 1e-9)
    print(
        f"\n{len(samples):,} samples over {hours * 60:.0f} minutes ({rate:.0f} Hz), "
        f"{windows} windows of {WINDOW_S:g} s"
    )
    print(
        f"strict double nods (D-018): {strict} ({strict / hours:.1f} an hour, "
        f"{strict / windows:.2%} of windows; the target is under 1%)"
    )
    print(f"the plan's v1 nods: {v1} windows ({v1 / hours:.1f} an hour)")
    print(f"shakes: {shakes} windows ({shakes / windows:.2%}); each only hands off")
    return 0


if __name__ == "__main__":
    sys.exit(main())
