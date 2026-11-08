"""Challenge words for tier 2 (Phase 2, milestone 5; P-08 revised, D-029)."""

from __future__ import annotations

import itertools

import pytest

from earshot.voice import challenge


def test_about_200_words() -> None:
    assert len(challenge.words()) == 200
    assert len(set(challenge.words())) == 200


def test_no_two_words_sound_alike() -> None:
    for a, b in itertools.combinations(challenge.words(), 2):
        assert challenge.code_distance(a, b) >= challenge.MIN_CODE_DISTANCE, (a, b)


def test_no_word_sounds_like_an_everyday_reply() -> None:
    for word in challenge.words():
        for everyday in challenge.EVERYDAY:
            assert challenge.code_distance(word, everyday) >= challenge.MIN_CODE_DISTANCE, (
                word,
                everyday,
            )


@pytest.mark.filterwarnings(
    "ignore::FutureWarning", "ignore::UserWarning", "ignore::DeprecationWarning"
)
def test_kokoro_can_say_every_word() -> None:
    en = pytest.importorskip("misaki.en")  # the voice group, on the Mac
    g2p = en.G2P(trf=False, british=False, fallback=None)
    for word in challenge.words():
        _, tokens = g2p(word)
        assert all(t.phonemes for t in tokens if str(t.text).strip()), word


def test_pick_is_one_of_the_words() -> None:
    assert {challenge.pick() for _ in range(50)} <= set(challenge.words())


@pytest.mark.parametrize(
    ("reply", "accepted"),
    [
        ("approve harbor", True),
        ("Approve harbor.", True),
        ("A proof, harbor!", True),  # the carrier word is ignored: the recogniser mangles it
        ("Uproom harbor", True),
        ("harbor", True),
        ("approve harbour", True),  # the same sound
        ("approve harbor please", False),  # the word must end the reply
        ("don't approve harbor", False),  # a negation
        ("no harbor", False),
        ("approve lantern", False),  # another challenge word
        ("approve harvest", False),  # close in spelling, not in sound
        ("yes", False),  # a bare yes never answers a challenge
        ("approve it", False),
        ("okay then I guess approve harbor", False),  # more than four words
        ("", False),
    ],
)
def test_matching(reply: str, accepted: bool) -> None:
    assert "harbor" in challenge.words()
    assert challenge.matches(reply, "harbor") is accepted
