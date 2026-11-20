"""The voiceprint (Phase 2, milestone 6): profiles, verdicts, and ECAPA's features in numpy."""

from __future__ import annotations

import math
import stat
from pathlib import Path

import pytest

from earwarden.voice import voiceprint


def test_a_profile_is_the_mean_of_unit_embeddings() -> None:
    profile = voiceprint.build_profile([[3.0, 0.0], [0.0, 0.5]])
    assert profile.embedding == pytest.approx((math.sqrt(0.5), math.sqrt(0.5)))
    assert profile.phrases == 2
    assert not profile.calibrated


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (0.62, "match"),
        (0.50, "match"),
        (0.47, "borderline"),
        (0.45, "borderline"),
        (0.30, "mismatch"),
    ],
)
def test_verdicts(score: float, expected: str) -> None:
    profile = voiceprint.build_profile([[1.0, 0.0]])  # threshold 0.50, borderline from 0.45
    assert voiceprint.verdict(score, profile) == expected


def test_cosine() -> None:
    assert voiceprint.cosine([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert voiceprint.cosine([1.0, 0.0], [0.0, 2.0]) == pytest.approx(0.0)
    assert voiceprint.cosine([0.0, 0.0], [1.0, 0.0]) == 0.0


def test_the_profile_is_private_and_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "home" / "voiceprint.json"
    profile = voiceprint.build_profile([[0.1, 0.2, 0.3], [0.3, 0.2, 0.1]])
    voiceprint.save(profile, path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert voiceprint.load(path) == profile
    path.write_text("{not json")
    assert voiceprint.load(path) is None
    assert voiceprint.load(tmp_path / "missing.json") is None


def test_ecapa_features_have_the_right_shape_and_no_mean() -> None:
    np = pytest.importorskip("numpy")  # the voice group, on the Mac
    rng = np.random.default_rng(1)
    audio = (rng.standard_normal(16_000) * 0.1).astype(np.float32)  # one second
    features = voiceprint.fbank(audio)
    assert features.shape == (101, voiceprint.N_MELS)  # 10 ms frames, centred
    assert np.allclose(features.mean(axis=0), 0.0, atol=1e-4)  # sentence mean normalisation
    assert np.array_equal(features, voiceprint.fbank(audio))


def test_enrollment_builds_and_saves_a_profile(tmp_path: Path) -> None:
    from earwarden.voice import enroll

    prompts: list[str] = []
    vectors = iter([[1.0, 0.1], [0.9, 0.0], [1.0, -0.1], [0.95, 0.05], [0.0, 1.0]])

    def record(prompt: str) -> object | None:
        prompts.append(prompt)
        return None if len(prompts) == 2 else object()  # the second prompt goes unheard once

    said: list[str] = []
    profile = enroll.enroll(
        record, lambda clip: next(vectors), tmp_path / "voiceprint.json", said.append, 3, 2
    )
    assert profile is not None
    assert profile.phrases == 3
    assert prompts[2].startswith("Again: approve ")  # asked again after nothing was heard
    assert voiceprint.load(tmp_path / "voiceprint.json") == profile
    assert any("held-out phrases scored" in line for line in said)
    assert any("under the threshold" in line for line in said)  # the [0, 1] phrase


def test_too_few_phrases_make_no_profile(tmp_path: Path) -> None:
    from earwarden.voice import enroll

    said: list[str] = []
    profile = enroll.enroll(lambda p: None, lambda c: [1.0], tmp_path / "v.json", said.append, 3, 0)
    assert profile is None
    assert not (tmp_path / "v.json").exists()
