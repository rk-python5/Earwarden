"""The replay attack, on the Mac (Phase 4, milestone 6; `docs/redteam.md`).

    uv run python dev/redteam_replay.py --home .tools/earshot [--clips DIR] [--runs 6]

With `earshotd --voice --pin-voice` running and the AirPods in, it sends tier-2 test requests
and, each time Earshot asks, plays one of your recorded "approve <word>" phrases through the
Mac's own speaker, as an attacker with a recording of you would. The fresh challenge word never
matches the recording, so every run must end on the screen. It prints each run's result and the
audit log's view of it. Keep the AirPods in: the replay must reach their mic from the room.

The clips come from `earshot enroll --save-clips DIR` (the `profile` and `held-out` folders).
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
import threading
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from earshot import audit, paths  # noqa: E402

ASK_DELAY_S = 6.0  # about when the question ends and the tone sounds, after the request is sent


def speaker() -> int | None:
    """The built-in speaker, so the replay comes from the room and not from inside the AirPods."""
    for index, device in enumerate(sd.query_devices()):
        name = str(device["name"])
        if "speaker" in name.lower() and int(device["max_output_channels"]) > 0:
            return index
    return None


def play(path: Path, device: int | None) -> None:
    with wave.open(str(path)) as recording:
        rate = recording.getframerate()
        audio = np.frombuffer(recording.readframes(recording.getnframes()), dtype=np.int16)
    sd.play(audio.astype(np.float32) / 32768, rate, device=device)
    sd.wait()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", required=True)
    parser.add_argument("--clips", default=None, help="your recorded phrases (WAV)")
    parser.add_argument("--runs", type=int, default=6)
    args = parser.parse_args()
    where = paths.resolve(args.home)
    clips = sorted(Path(args.clips or (where.state_dir / "enroll")).rglob("*.wav"))
    if not clips:
        print("No recorded phrases found; run earshot enroll --save-clips first.")
        return 1
    out = speaker()
    name = sd.query_devices(out)["name"] if out is not None else "the default output"
    print(f"Playing through {name}.")
    approvals = 0
    for run in range(1, args.runs + 1):
        clip = random.choice(clips)  # noqa: S311 - not security: which recording to replay
        before = sum(1 for _ in audit.AuditLog(where.audit_dir, audit.load_key(where)).records())
        test = subprocess.Popen(  # noqa: S603 - our own command
            [sys.executable, "-m", "earshot.cli", "test", "--home", args.home, "--tier", "2"],
            stdout=subprocess.PIPE,
            text=True,
        )
        timer = threading.Timer(ASK_DELAY_S, play, args=(clip, out))
        timer.start()
        output = test.communicate(timeout=120)[0].strip().splitlines()
        timer.cancel()
        result = output[-1] if output else "?"
        records = list(audit.AuditLog(where.audit_dir, audit.load_key(where)).records())[before:]
        heard = [r.get("transcript") for r in records]
        allowed = "allow" in result
        approvals += allowed
        print(
            f"run {run}: replayed {clip.name}; {result}; heard {heard}"
            + ("  <-- APPROVED" if allowed else "")
        )
    print(
        f"\n{approvals} approvals in {args.runs} replays"
        + (": FAIL" if approvals else ": every replay ended on the screen")
    )
    print(json.dumps({"runs": args.runs, "approvals": approvals}))
    return 1 if approvals else 0


if __name__ == "__main__":
    sys.exit(main())
