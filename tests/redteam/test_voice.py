"""Attacks on the voice path: tier 3 with every reply, replays, splices and the wrong voice."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from test_voice_decider import Away, FakeVoice, pending

from earshot.voice import challenge, intents
from earshot.voice.decider import CUT_OFF, NOD, SHAKE, Heard, Speaker, VoiceDecider

PUSH = {"command": "git push --force origin main"}
INSTALL = {"command": "pip install httpx"}
EVERY_APPROVAL = [
    *sorted(intents.APPROVE),
    "approve harbor",
    "approve it now",
    Heard("", NOD, 0),
    Heard("yes", "parakeet", 50, Speaker(0.99, "match")),
]


def decide(voice: FakeVoice, item: Any, enrolled: bool = True) -> Any:
    voice.enrolled = enrolled
    decider = VoiceDecider(voice, Away(), reannounce_s=0, reannounce_max=2)
    return asyncio.run(decider(item))


@pytest.mark.parametrize("reply", EVERY_APPROVAL, ids=str)
def test_tier_3_is_never_approved_by_any_reply(reply: Any) -> None:
    voice = FakeVoice([reply, reply, reply])
    answer = decide(voice, pending("Bash", PUSH))
    assert answer.outcome == "handoff"
    assert voice.listens == 0  # it never even listened
    assert voice.said[-1].endswith("It's on your screen.")


def match(word: str) -> Heard:
    return Heard(f"approve {word}", "parakeet", 50, Speaker(0.9, "match"))


def test_a_replay_of_an_old_challenge_word_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(challenge, "pick", lambda: "harbor")
    old = match("lantern")  # recorded last time, in rehaan's own voice
    answer = decide(FakeVoice([old, old, old]), pending("Bash", INSTALL))
    assert answer.outcome == "handoff"


def test_a_plain_yes_in_the_right_voice_never_answers_a_challenge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(challenge, "pick", lambda: "harbor")
    yes = Heard("yes", "parakeet", 50, Speaker(0.95, "match"))
    answer = decide(FakeVoice([yes, yes, yes]), pending("Bash", INSTALL))
    assert answer.outcome == "handoff"


@pytest.mark.parametrize(
    "said",
    [
        "approve harbor and also push everything",  # a long recording with the word in it
        "no approve harbor",
        "don't approve harbor",
        "approve harbor no",
        "approve orchard",  # a sound-alike
        "approve",
        "I said approve harbor earlier today",
    ],
)
def test_a_spliced_or_hedged_challenge_reply_is_refused(
    said: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(challenge, "pick", lambda: "harbor")
    heard = Heard(said, "parakeet", 50, Speaker(0.9, "match"))
    answer = decide(FakeVoice([heard, heard, heard]), pending("Bash", INSTALL))
    assert answer.outcome != "allow", said


@pytest.mark.parametrize("verdict", ["mismatch", "borderline"])
def test_the_right_word_in_another_voice_goes_to_the_screen(
    verdict: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(challenge, "pick", lambda: "harbor")
    heard = Heard("approve harbor", "parakeet", 50, Speaker(0.3, verdict))  # type: ignore[arg-type]
    voice = FakeVoice([heard])
    answer = decide(voice, pending("Bash", INSTALL))
    assert answer.outcome == "handoff"
    assert "Didn't catch that clearly" in voice.said[-1]


def test_a_challenge_reply_without_a_voiceprint_score_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(challenge, "pick", lambda: "harbor")
    heard = Heard("approve harbor", "parakeet", 50, None)  # the scorer failed or was skipped
    assert decide(FakeVoice([heard]), pending("Bash", INSTALL)).outcome == "handoff"


def test_a_cut_off_reply_is_never_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(challenge, "pick", lambda: "harbor")
    early = Heard("approve harbor", CUT_OFF, 0, Speaker(0.9, "match"))
    answer = decide(FakeVoice([early, early, early]), pending("Bash", INSTALL))
    assert answer.outcome == "handoff"
    assert decide(FakeVoice([Heard("yes", CUT_OFF, 0)] * 3), pending()).outcome == "handoff"


def test_a_nod_never_approves_tier_2_and_a_shake_never_denies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(challenge, "pick", lambda: "harbor")
    nod = Heard("", NOD, 0)
    assert decide(FakeVoice([nod, nod, nod]), pending("Bash", INSTALL)).outcome == "handoff"
    assert decide(FakeVoice([Heard("", SHAKE, 0)]), pending()).outcome == "handoff"


def test_tier_2_without_an_enrolled_voiceprint_is_never_asked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(challenge, "pick", lambda: "harbor")
    voice = FakeVoice([match("harbor")])
    assert decide(voice, pending("Bash", INSTALL), enrolled=False).outcome == "handoff"
    assert voice.listens == 0


def test_the_word_alone_is_accepted_by_design(monkeypatch: pytest.MonkeyPatch) -> None:
    # P-08 (D-029): the challenge word decides, and the carrier word is ignored. "harbor" on its
    # own, in your voice, right after the tone, is you.
    monkeypatch.setattr(challenge, "pick", lambda: "harbor")
    heard = Heard("harbor", "parakeet", 50, Speaker(0.9, "match"))
    assert decide(FakeVoice([heard]), pending("Bash", INSTALL)).outcome == "allow"


def test_a_colleagues_yes_at_tier_1_is_the_documented_limit() -> None:
    # The spec accepts this: tier 1 is low risk, and the window is short. It's here so the
    # limit is tested, not forgotten.
    other = Heard("yes", "parakeet", 50, Speaker(0.2, "mismatch"))
    assert decide(FakeVoice([other]), pending()).outcome == "allow"
