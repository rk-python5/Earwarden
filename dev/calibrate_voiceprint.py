"""Calibrate the voiceprint's threshold against other voices (milestone 6; the spec, Q-5).

    uv run python dev/calibrate_voiceprint.py --home .tools/earshot \\
        --yours .tools/earshot/enroll --impostors .tools/earshot/calibration [--write]

- `--yours`: your held-out phrases (`earshot enroll --save-clips DIR`), as WAV files.
- `--impostors`: other people's phrases (`earshot enroll --impostor NAME`), one folder each.
- `--enroll-from DIR --enroll N`: build the profile from the first N phrases in DIR instead of
  using your enrolled one. This is how Step 0's recordings are checked:

    R=spikes/speech/out/replies
    uv run python dev/calibrate_voiceprint.py --enroll-from $R/you --enroll 5 \\
        --yours $R/you --impostors $R/friend

It prints every score, the equal error rate, and the threshold that accepts at most 2% of the
impostors' phrases, with your false-reject rate there. `--write` saves that threshold into your
profile and marks it calibrated. Each clip is trimmed the way the live path trims answers.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from earshot import paths  # noqa: E402
from earshot.voice import voiceprint  # noqa: E402
from earshot.voice.mac import VAD_MODEL  # noqa: E402

MAX_IMPOSTORS_ACCEPTED = 0.02


def read(path: Path) -> np.ndarray:
    with wave.open(str(path)) as recording:
        raw = recording.readframes(recording.getnframes())
        rate = recording.getframerate()
    audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768
    if rate != voiceprint.RATE:
        target = np.linspace(0, len(audio) / rate, int(len(audio) / rate * voiceprint.RATE))
        audio = np.interp(target, np.arange(len(audio)) / rate, audio).astype(np.float32)
    return audio


def trim(audio: np.ndarray) -> np.ndarray:
    """The answer as the live path keeps it: Silero's speech, with a quarter second either side.

    A click, or a breath, isn't speech to Silero, so it's left out, as the live path ignores it.
    """
    import mlx.core as mx
    from mlx_audio.vad import load

    global _VAD
    if _VAD is None:
        _VAD = load(VAD_MODEL)
    speech = _VAD.get_speech_timestamps(
        mx.array(audio),
        sample_rate=voiceprint.RATE,
        min_speech_duration_ms=100,
        return_seconds=True,
    )
    if not speech:
        return audio
    start = max(0, int((float(speech[0]["start"]) - 0.25) * voiceprint.RATE))
    return audio[start : int((float(speech[-1]["end"]) + 0.25) * voiceprint.RATE)]


_VAD = None


def wavs(folder: Path) -> list[Path]:
    return sorted(folder.rglob("*.wav"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", help="Earshot's home, as for earshotd")
    parser.add_argument("--yours", required=True, help="your held-out phrases (WAV)")
    parser.add_argument("--impostors", required=True, help="other voices' phrases (WAV)")
    parser.add_argument("--enroll-from", help="build the profile from this folder instead")
    parser.add_argument("--enroll", type=int, default=12, help="phrases for that profile")
    parser.add_argument("--only", default="ch-", help="only files whose name starts with this")
    parser.add_argument("--write", action="store_true", help="save the threshold into your profile")
    args = parser.parse_args()
    where = paths.resolve(args.home)
    embedder = voiceprint.Embedder(where.models_dir / voiceprint.MODEL)

    def embed(path: Path) -> list[float]:
        return embedder.embed(trim(read(path)))

    def pick(folder: str) -> list[Path]:
        return [p for p in wavs(Path(folder)) if p.name.startswith(args.only)]

    enrolled: list[Path] = []
    if args.enroll_from:
        enrolled = pick(args.enroll_from)[: args.enroll]
        profile = voiceprint.build_profile([embed(p) for p in enrolled])
    else:
        loaded = voiceprint.load(where.voiceprint)
        if loaded is None:
            print(f"No voiceprint at {where.voiceprint}: run earshot enroll first.")
            return 1
        profile = loaded
    yours = {p: voiceprint.cosine(embed(p), profile.embedding) for p in pick(args.yours)}
    yours = {p: s for p, s in yours.items() if p not in enrolled}
    theirs = {p: voiceprint.cosine(embed(p), profile.embedding) for p in pick(args.impostors)}
    if not yours or not theirs:
        print("Need some of your held-out phrases and some impostors' phrases.")
        return 1
    for label, scores in (("yours", yours), ("impostors", theirs)):
        print(f"{label}:")
        for path, score in sorted(scores.items(), key=lambda item: item[1]):
            print(f"  {score:.3f}  {path.parent.name}/{path.name}")

    mine, others = sorted(yours.values()), sorted(theirs.values(), reverse=True)
    allowed = int(MAX_IMPOSTORS_ACCEPTED * len(others))
    threshold = round(others[allowed] + 0.001, 3) if allowed < len(others) else others[-1]
    rejected = sum(s < threshold for s in mine) / len(mine)
    candidates = sorted({*mine, *others})
    eer = min(
        (max(sum(s < t for s in mine) / len(mine), sum(s >= t for s in others) / len(others)), t)
        for t in candidates
    )
    print(f"\nyours: lowest {mine[0]:.3f}, median {statistics.median(mine):.3f}")
    print(f"impostors: highest {others[0]:.3f}, median {statistics.median(others):.3f}")
    print(f"gap: {mine[0] - others[0]:+.3f}")
    print(f"equal error rate: about {eer[0]:.1%}, at {eer[1]:.3f}")
    print(
        f"threshold at most {MAX_IMPOSTORS_ACCEPTED:.0%} impostors: {threshold:.3f}, "
        f"rejecting {rejected:.0%} of your phrases ({len(others)} impostor phrases)"
    )
    if args.write:
        calibrated = profile._replace(
            threshold=threshold,
            borderline=round(threshold - voiceprint.BORDERLINE_BAND, 3),
            calibrated=True,
        )
        voiceprint.save(calibrated, where.voiceprint)
        print(f"Saved the threshold to {where.voiceprint}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
