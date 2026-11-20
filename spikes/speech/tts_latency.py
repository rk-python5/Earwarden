# /// script
# requires-python = ">=3.11,<3.13"
# dependencies = [
#     "mlx-audio==0.6.4",
#     "misaki[en]==0.9.4",
#     "en-core-web-sm @ https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl",
#     "numpy",
#     "sounddevice>=0.5",
# ]
# ///
"""Kokoro on the M2: time to first audio, synthesis speed, memory. macOS on Apple Silicon only.

    uv run spikes/speech/tts_latency.py              # measure the summaries in speech_data.py
    uv run spikes/speech/tts_latency.py --save       # also write WAVs to out/tts/ to listen to
    uv run spikes/speech/tts_latency.py --play       # also play each one on the default output
    uv run spikes/speech/tts_latency.py --save --no-fallback   # hear what's lost without espeak-ng

Text is streamed sentence by sentence, as the plan specifies. "First audio" is the time until the
first sentence's samples are ready; playback adds the Bluetooth output delay on top (measured by
spikes/audio_io). Note: misaki[en] 0.9.4 bundles espeak-ng (GPL) through espeakng-loader. That's
fine for a local spike but not for Earwarden itself (decisions.md, P-04).
"""

from __future__ import annotations

import argparse
import platform
import resource
import statistics
import sys
import time
import wave
from pathlib import Path

import numpy as np
from speech_data import SUMMARIES

OUT = Path(__file__).resolve().parent / "out" / "tts"
SENTENCES = r"(?<=[.!?;:])\s+"
SAMPLE_RATE = 24_000


def write_wav(path: Path, audio: np.ndarray, rate: int) -> None:
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(rate)
        f.writeframes(pcm.tobytes())


def p95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(0.95 * (len(ordered) - 1)))]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="mlx-community/Kokoro-82M-bf16")
    parser.add_argument("--voice", default="af_heart")
    parser.add_argument("--speed", type=float, default=1.1)
    parser.add_argument("--repeats", type=int, default=3, help="passes over the summaries")
    parser.add_argument("--save", action="store_true")
    parser.add_argument("--play", action="store_true")
    parser.add_argument(
        "--no-fallback",
        action="store_true",
        help="turn off the espeak-ng fallback, as in the plan's licence-safe setup",
    )
    args = parser.parse_args()

    if sys.platform != "darwin" or platform.machine() != "arm64":
        sys.exit("MLX needs macOS on Apple Silicon.")

    import mlx.core as mx
    from mlx_audio.tts.utils import load as load_tts

    start = time.perf_counter()
    model = load_tts(args.model)
    load_s = time.perf_counter() - start
    for _ in model.generate("Warming up the voice.", voice=args.voice, speed=args.speed):
        pass
    if args.no_fallback:
        model._get_pipeline("a").g2p.fallback = None  # words without phonemes are now skipped

    if args.save:
        OUT.mkdir(parents=True, exist_ok=True)
    first_ms: list[float] = []
    rtf: list[float] = []
    print(f"{'first (ms)':>10} {'total (ms)':>10} {'audio (s)':>9}  summary")
    for rep in range(args.repeats):
        for index, text in enumerate(SUMMARIES):
            chunks = []
            first = None
            start = time.perf_counter()
            for result in model.generate(
                text, voice=args.voice, speed=args.speed, split_pattern=SENTENCES
            ):
                if first is None:
                    first = (time.perf_counter() - start) * 1000
                chunks.append(np.array(result.audio, dtype=np.float32))
            total = (time.perf_counter() - start) * 1000
            audio = np.concatenate(chunks)
            seconds = len(audio) / SAMPLE_RATE
            if first is None:
                sys.exit(f"No audio for: {text}")
            first_ms.append(first)
            rtf.append(total / 1000 / seconds)
            print(f"{first:10.0f} {total:10.0f} {seconds:9.1f}  {text[:60]}")
            if rep == 0 and args.save:
                write_wav(OUT / f"{index:02d}.wav", audio, SAMPLE_RATE)
            if rep == 0 and args.play:
                import sounddevice as sd

                sd.play(audio, SAMPLE_RATE)
                sd.wait()

    peak_rss_gb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e9  # bytes on macOS
    print()
    print(f"Model load:              {load_s:.1f} s")
    print(
        f"Time to first audio:     median {statistics.median(first_ms):.0f} ms, "
        f"p95 {p95(first_ms):.0f} ms (budget 200 ms)"
    )
    print(f"Real-time factor:        median {statistics.median(rtf):.3f}")
    print(f"Peak MLX memory:         {mx.get_peak_memory() / 1e9:.2f} GB")
    print(f"Peak process RSS:        {peak_rss_gb:.2f} GB")
    if args.save:
        print(f"WAVs in {OUT}.")
        if args.no_fallback:
            print("Listen for skipped words, for example 'quickstart' in 01.wav.")


if __name__ == "__main__":
    main()
