"""Record a few seconds from the mic and say whether real audio came through. macOS.

Run by launchd (through agent.py) or straight from Terminal for comparison. It writes one JSON
result and always exits 0. A recording of exact zeros usually means macOS denied the mic without
showing a prompt.

Needs sounddevice and numpy in the interpreter that runs it; agent.py's setup installs them.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any


def record(device: str | None, seconds: float) -> dict[str, Any]:
    import numpy as np
    import sounddevice as sd

    index = None
    if device:
        for i, info in enumerate(sd.query_devices()):
            if device.lower() in info["name"].lower() and info["max_input_channels"] > 0:
                index = i
                break
    info = sd.query_devices(index, kind="input")
    rate = int(info["default_samplerate"])
    audio = sd.rec(int(seconds * rate), samplerate=rate, channels=1, device=index, dtype="float32")
    sd.wait()
    samples = audio[:, 0]
    return {
        "device": info["name"],
        "rate": rate,
        "peak": float(np.max(np.abs(samples))),
        "rms": float(np.sqrt(np.mean(np.square(samples)))),
        "all_zero": bool(not np.any(samples)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--device", help="part of the input device's name; default input if absent")
    parser.add_argument("--seconds", type=float, default=3.0)
    args = parser.parse_args()

    result: dict[str, Any] = {
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "executable": sys.executable,
        "resolved_executable": str(Path(sys.executable).resolve()),
        "python": sys.version.split()[0],
        "pid": os.getpid(),
        "ppid": os.getppid(),
        "started_by_launchd": os.getppid() == 1,
    }
    try:
        result.update(record(args.device, args.seconds))
        result["verdict"] = "denied (silence)" if result["all_zero"] else "audio came through"
    except Exception as exc:  # report every failure; the point is to see what breaks
        result["error"] = repr(exc)
        result["verdict"] = "error"
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
