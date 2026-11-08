"""The voiceprint: is it you answering? (Phase 2, milestone 6; D-014, the spec's "Voiceprint").

SpeechBrain's ECAPA-TDNN (Apache 2.0) turns a reply into a 192-number embedding, compared with your
enrolled profile by cosine similarity. It runs on onnxruntime, so the daemon needs no PyTorch:

- `fbank` computes ECAPA's input in numpy, the way SpeechBrain does: 25 ms Hamming windows every
  10 ms, the power spectrum, 80 triangular mel filters, log to dB with an 80 dB floor, then the
  phrase's mean taken off each band. `dev/export_ecapa.py` exports the network and checks this
  matches SpeechBrain's own features.
- The profile is the mean of your enrollment phrases' embeddings (`earshot enroll`), kept in
  `voiceprint.json` with only your user able to read it. No audio is kept.
- A score at or over the threshold is a match. Just under it is borderline ("Didn't catch that
  clearly; it's on your screen"). Below that, it's someone else. The threshold starts at Step 0's
  mid-point and is set properly by calibration against other voices (`dev/calibrate_voiceprint.py`,
  Q-5), aiming for at most 2% of impostors accepted.
"""

from __future__ import annotations

import json
import math
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, NamedTuple

RATE = 16_000
N_FFT = 400
HOP = 160
N_MELS = 80
TOP_DB = 80.0
AMIN = 1e-10
MODEL = "ecapa_embedding.onnx"  # from dev/export_ecapa.py, in the home's models folder
# Step 0: your lowest held-out score 0.553, a friend's highest 0.440 (spikes/RESULTS.md, section 6)
DEFAULT_THRESHOLD = 0.50
BORDERLINE_BAND = 0.05

Verdict = Literal["match", "borderline", "mismatch"]


class Profile(NamedTuple):
    embedding: tuple[float, ...]  # unit length
    threshold: float
    borderline: float  # scores from here up to the threshold are borderline
    phrases: int
    enrolled_at: str
    calibrated: bool  # False until dev/calibrate_voiceprint.py sets the threshold


def cosine(a: tuple[float, ...] | list[float], b: tuple[float, ...] | list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norms = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norms if norms else 0.0


def unit(vector: list[float]) -> tuple[float, ...]:
    norm = math.sqrt(sum(x * x for x in vector)) or 1.0
    return tuple(x / norm for x in vector)


def build_profile(embeddings: list[list[float]], threshold: float = DEFAULT_THRESHOLD) -> Profile:
    """Your profile: the mean of your phrases' embeddings, each made unit length first."""
    units = [unit(e) for e in embeddings]
    mean = [sum(column) / len(units) for column in zip(*units, strict=True)]
    when = datetime.now(UTC).isoformat(timespec="seconds")
    return Profile(unit(mean), threshold, threshold - BORDERLINE_BAND, len(units), when, False)


def verdict(score: float, profile: Profile) -> Verdict:
    if score >= profile.threshold:
        return "match"
    return "borderline" if score >= profile.borderline else "mismatch"


def save(profile: Profile, path: Path) -> None:
    """Write the profile so only your user can read it: it's a biometric template."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(profile._asdict(), indent=1).encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
    path.chmod(0o600)


def load(path: Path) -> Profile | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return Profile(
            tuple(float(x) for x in data["embedding"]),
            float(data["threshold"]),
            float(data["borderline"]),
            int(data["phrases"]),
            str(data["enrolled_at"]),
            bool(data["calibrated"]),
        )
    except (OSError, ValueError, KeyError, TypeError):
        return None


def fbank(audio: Any) -> Any:
    """ECAPA's input features for 16 kHz mono audio, as SpeechBrain computes them: (frames, 80)."""
    import numpy as np

    wav = np.asarray(audio, dtype=np.float64)
    padded = np.pad(wav, (N_FFT // 2, N_FFT // 2))  # torch.stft(center=True, pad_mode="constant")
    count = 1 + (len(padded) - N_FFT) // HOP
    index = np.arange(N_FFT)[None, :] + HOP * np.arange(count)[:, None]
    window = 0.54 - 0.46 * np.cos(2 * np.pi * np.arange(N_FFT) / N_FFT)  # periodic Hamming
    power = np.abs(np.fft.rfft(padded[index] * window, n=N_FFT)) ** 2
    mel = np.dot(power, _mel_filters())
    db = 10.0 * np.log10(np.maximum(mel, AMIN))
    db = np.maximum(db, db.max() - TOP_DB)
    return (db - db.mean(axis=0)).astype(np.float32)  # sentence mean normalisation, no std


def _mel_filters() -> Any:
    """SpeechBrain's triangular filterbank: (201 frequency bins, 80 mel bands)."""
    import numpy as np

    def to_mel(hz: Any) -> Any:
        return 2595 * np.log10(1 + hz / 700)

    def to_hz(mel: Any) -> Any:
        return 700 * (10 ** (mel / 2595) - 1)

    hz = to_hz(np.linspace(to_mel(0.0), to_mel(RATE / 2), N_MELS + 2))
    band = (hz[1:] - hz[:-1])[:-1]
    central = hz[1:-1]
    freqs = np.linspace(0, RATE // 2, N_FFT // 2 + 1)
    slope = (freqs[None, :] - central[:, None]) / band[:, None]
    return np.maximum(0.0, np.minimum(slope + 1.0, 1.0 - slope)).T


class Embedder:
    """ECAPA on onnxruntime: 16 kHz audio in, a 192-number embedding out (about 40 ms)."""

    def __init__(self, model: Path) -> None:
        import onnxruntime as ort

        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        self.session = ort.InferenceSession(str(model), options, providers=["CPUExecutionProvider"])
        self.input = self.session.get_inputs()[0].name

    def embed(self, audio: Any) -> list[float]:
        features = fbank(audio)[None, :, :]
        output = self.session.run(None, {self.input: features})[0]
        return [float(x) for x in output.reshape(-1)]
