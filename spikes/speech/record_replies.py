# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "scipy", "sounddevice>=0.5"]
# ///
"""Record the Step 0 reply set through the AirPods mic. macOS.

    uv run spikes/speech/record_replies.py --condition quiet
    uv run spikes/speech/record_replies.py --condition noisy        # kitchen, street or TV on
    uv run spikes/speech/record_replies.py --condition quiet --only yes,no   # redo a few

Each condition is 50 replies (speech_data.REPLIES), so both together make the plan's 100. Saves
16 kHz mono WAVs to out/replies/<condition>/<id>.wav, and labels to out/replies/labels.csv. The
mic stays open for the whole session, so the AirPods switch to headset mode once, before the
first prompt, and never clip a reply. Recordings stay on your Mac; they're git-ignored.
"""

from __future__ import annotations

import argparse
import csv
import queue
import sys
import threading
import time
import wave
from math import gcd
from pathlib import Path
from typing import Any

import numpy as np
from speech_data import REPLIES

OUT = Path(__file__).resolve().parent / "out" / "replies"
TARGET_RATE = 16_000
FIELDS = ["condition", "id", "file", "text", "intent", "challenge"]


def find_input(name: str) -> int:
    import sounddevice as sd

    devices: Any = sd.query_devices()
    for index, device in enumerate(devices):
        if name.lower() in device["name"].lower() and device["max_input_channels"] > 0:
            return index
    inputs = [d["name"] for d in devices if d["max_input_channels"] > 0]
    sys.exit(f"No input device matching {name!r}. Inputs: {inputs}")


def to_target_rate(audio: np.ndarray, rate: int) -> np.ndarray:
    if rate == TARGET_RATE:
        return audio
    from scipy.signal import resample_poly

    g = gcd(rate, TARGET_RATE)
    return np.asarray(resample_poly(audio, TARGET_RATE // g, rate // g), dtype=np.float32)


def write_wav(path: Path, audio: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(TARGET_RATE)
        f.writeframes(pcm.tobytes())


class Recorder:
    """One input stream for the whole session; record() returns the next N seconds."""

    def __init__(self, device: int, rate: int) -> None:
        import sounddevice as sd

        self.rate = rate
        self.chunks: queue.Queue[np.ndarray] = queue.Queue()
        self.capturing = threading.Event()

        def callback(indata: np.ndarray, frames: int, time_info: Any, status: Any) -> None:
            if self.capturing.is_set():
                self.chunks.put(indata[:, 0].copy())

        self.stream = sd.InputStream(
            device=device, channels=1, samplerate=rate, dtype="float32", callback=callback
        )

    def __enter__(self) -> Recorder:
        self.stream.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stream.stop()
        self.stream.close()

    def record(self, seconds: float) -> np.ndarray:
        while not self.chunks.empty():
            self.chunks.get_nowait()
        self.capturing.set()
        time.sleep(seconds)
        self.capturing.clear()
        parts = []
        while not self.chunks.empty():
            parts.append(self.chunks.get_nowait())
        return np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)


def load_labels(path: Path) -> dict[tuple[str, str], dict[str, str]]:
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as f:
        return {(row["condition"], row["id"]): row for row in csv.DictReader(f)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--condition", required=True, help="for example quiet or noisy")
    parser.add_argument("--device", default="AirPods", help="part of the input device's name")
    parser.add_argument("--seconds", type=float, default=3.0, help="length of each recording")
    parser.add_argument("--only", help="comma-separated reply ids to (re)record")
    args = parser.parse_args()

    import sounddevice as sd

    wanted = set(args.only.split(",")) if args.only else None
    replies = [r for r in REPLIES if wanted is None or r.id in wanted]
    device = find_input(args.device)
    info: Any = sd.query_devices(device)
    rate = int(info["default_samplerate"])
    print(f"Recording from {info['name']} at {rate} Hz, {args.seconds:g} s per reply.")
    print("Speak naturally, as if answering Earshot. Ctrl-C stops; finished replies are kept.")

    labels_path = OUT / "labels.csv"
    labels = load_labels(labels_path)
    try:
        with Recorder(device, rate) as recorder:
            time.sleep(1.0)  # let the headset-mode switch settle before the first prompt
            for number, reply in enumerate(replies, start=1):
                cue = f"   (Earshot asked for: {reply.challenge})" if reply.challenge else ""
                print(f"\n[{number}/{len(replies)}] Say: “{reply.text}”{cue}")
                while True:
                    input("  Press Enter, then speak… ")
                    print("  ● recording", flush=True)
                    audio = recorder.record(args.seconds)
                    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
                    warning = "   very quiet: is the AirPods mic the input?" if peak < 0.02 else ""
                    print(f"  peak level {peak:.2f}{warning}")
                    if input("  Enter keeps it, r redoes it: ").strip().lower() != "r":
                        break
                file = Path(args.condition) / f"{reply.id}.wav"
                write_wav(OUT / file, to_target_rate(audio, rate))
                labels[(args.condition, reply.id)] = {
                    "condition": args.condition,
                    "id": reply.id,
                    "file": str(file),
                    "text": reply.text,
                    "intent": reply.intent,
                    "challenge": reply.challenge or "",
                }
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        OUT.mkdir(parents=True, exist_ok=True)
        with labels_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(sorted(labels.values(), key=lambda r: (r["condition"], r["id"])))
        print(f"{len(labels)} labelled recordings in {labels_path}")


if __name__ == "__main__":
    main()
