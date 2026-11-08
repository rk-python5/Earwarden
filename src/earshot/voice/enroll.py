"""`earshot enroll`: record your voiceprint through the AirPods (Phase 2, milestone 6).

Twelve phrases, about 45 seconds, in the same headset mode Earshot listens in: matching the channel
matters more than the model. Each prompt asks for a challenge phrase ("Say: approve harbor."), and
the reply is captured like any answer, so the same endpointer and voice detector trim it. Your
profile is the mean of their embeddings. A few more phrases are held out and scored against it as
a first check; calibration against other voices sets the real threshold (Q-5).

With `--save-clips`, the phrases are kept as WAV files for `dev/calibrate_voiceprint.py`. With
`--impostor NAME`, a friend records phrases for calibration only, and no profile is made.
"""

from __future__ import annotations

import random
import statistics
import wave
from collections.abc import Callable
from pathlib import Path
from typing import Any

from earshot.voice import challenge, voiceprint

Record = Callable[[str], Any]  # say a prompt, return the reply's 16 kHz audio or None
Embed = Callable[[Any], list[float]]
Report = Callable[[str], None]


def save_wav(path: Path, audio: Any) -> None:
    import numpy as np

    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(voiceprint.RATE)
        out.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())


def collect(
    record: Record,
    embed: Embed,
    words: list[str],
    report: Report,
    keep: Path | None = None,
    tries: int = 2,
) -> list[list[float]]:
    """One embedding per phrase heard; a phrase not heard after `tries` is skipped."""
    embeddings = []
    for number, word in enumerate(words, 1):
        clip = None
        for attempt in range(tries):
            clip = record(f"Say: approve {word}." if attempt == 0 else f"Again: approve {word}.")
            if clip is not None:
                break
        if clip is None:
            report(f"  {number:2}. approve {word}: nothing heard, skipped")
            continue
        embeddings.append(embed(clip))
        if keep is not None:
            save_wav(keep / f"{number:02d}-{word}.wav", clip)
        report(f"  {number:2}. approve {word}")
    return embeddings


def enroll(
    record: Record,
    embed: Embed,
    profile_path: Path,
    report: Report,
    phrases: int = 12,
    held_out: int = 6,
    keep: Path | None = None,
) -> voiceprint.Profile | None:
    words = random.sample(challenge.words(), phrases + held_out)
    got = collect(record, embed, words, report, keep)
    if len(got) < phrases:
        report(f"Only {len(got)} phrases were heard; {phrases} are needed. Run it again.")
        return None
    profile = voiceprint.build_profile(got[:phrases])
    scores = [voiceprint.cosine(e, profile.embedding) for e in got[phrases:]]
    if scores:
        middle = statistics.median(scores)
        report(
            f"Your held-out phrases scored {min(scores):.2f} at lowest, {middle:.2f} in the "
            f"middle; the threshold is {profile.threshold:.2f}."
        )
        if min(scores) < profile.threshold:
            report(
                "Some scored under the threshold, so tier 2 may ask you twice until calibration "
                "with other voices sets it properly (dev/calibrate_voiceprint.py)."
            )
    voiceprint.save(profile, profile_path)
    report(f"Saved your voiceprint to {profile_path}, readable only by you. No audio was kept.")
    return profile
