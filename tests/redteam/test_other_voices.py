"""Other people's voices against the enrolled voiceprint: a Mac-only check on real recordings.

It runs only where the recordings and the voiceprint model are (rehaan's Mac). In CI it skips.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOME = Path(os.environ.get("EARSHOT_HOME", ROOT / ".tools" / "earshot"))
FRIEND = ROOT / "spikes" / "speech" / "out" / "replies" / "friend"
DISGUISE = HOME / "disguise"


@pytest.mark.skipif(
    not (HOME / "voiceprint.json").exists() or not FRIEND.exists(),
    reason="needs the enrolled voiceprint and Step 0's recordings (rehaan's Mac)",
)
def test_no_other_voice_reaches_the_threshold() -> None:
    import sys

    sys.path.insert(0, str(ROOT / "dev"))
    import calibrate_voiceprint as cv  # type: ignore[import-not-found]

    from earshot.voice import voiceprint

    profile = voiceprint.load(HOME / "voiceprint.json")
    assert profile is not None
    embedder = voiceprint.Embedder(HOME / "models" / voiceprint.MODEL)
    others = sorted(FRIEND.glob("*.wav")) + sorted(DISGUISE.rglob("*.wav"))
    assert others
    scores = {
        p: voiceprint.cosine(embedder.embed(cv.trim(cv.read(p))), profile.embedding) for p in others
    }
    through = {p.name: round(s, 3) for p, s in scores.items() if s >= profile.threshold}
    assert through == {}, f"accepted at {profile.threshold}: {through}"
