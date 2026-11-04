"""The speech spike's labels match its intent rules, and only real approvals approve."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "spikes" / "speech"))

from speech_data import (
    CHALLENGE_WORDS,
    REPLIES,
    challenge_word_intent,
    intent,
    normalize,
    with_carrier_variants,
)


def test_fifty_unique_replies_per_condition() -> None:
    ids = [reply.id for reply in REPLIES]
    assert len(ids) == len(set(ids)) == 50


@pytest.mark.parametrize("reply", REPLIES, ids=lambda reply: reply.id)
def test_each_label_matches_the_rules_on_the_true_text(reply: object) -> None:
    text, label, challenge = reply.text, reply.intent, reply.challenge  # type: ignore[attr-defined]
    assert intent(text, challenge) == label


@pytest.mark.parametrize(
    "text",
    [
        "don't do it",
        "do it later",
        "no, don't",
        "yes, but run the tests first",
        "yes yes yes no",
        "I don't think you should do it",
        "approve orchid",
    ],
)
def test_approval_words_inside_other_replies_never_approve(text: str) -> None:
    assert intent(text) != "approve"
    assert intent(text, challenge="orchard") != "approve"


def test_a_challenge_needs_the_exact_phrase() -> None:
    assert intent("Approve orchard.", "orchard") == "approve"
    assert intent("yes", "orchard") == "unclear"
    assert intent("approve", "orchard") == "unclear"
    assert intent("no", "orchard") == "deny"


def test_normalize() -> None:
    assert normalize("Don\N{RIGHT SINGLE QUOTATION MARK}t  do it!") == "don't do it"
    assert normalize("API, yes.") == "api yes"


def test_challenge_words_are_distinct() -> None:
    assert len(set(CHALLENGE_WORDS)) == len(CHALLENGE_WORDS) == 10


@pytest.mark.parametrize(
    ("heard", "challenge", "expected"),
    [
        # Transcripts from rehaan's Mac runs
        ("A true compass.", "compass", "approve"),
        ("A proof harbour.", "harbor", "approve"),
        ("Approved marbles.", "marble", "approve"),
        ("Approved Harvard.", "harbor", "unclear"),
        ("Approved or none.", "tunnel", "unclear"),
        ("Approve orchid.", "orchard", "unclear"),
        ("Approved cobbler.", "copper", "unclear"),
        ("A broom lantern.", "harbor", "unclear"),
        ("Yes.", "compass", "unclear"),
        ("No.", "compass", "deny"),
        # A negation or a long reply never approves, even ending in the word
        ("Don't approve lantern.", "lantern", "unclear"),
        ("not lantern", "lantern", "unclear"),
        ("I really do not want to approve this lantern", "lantern", "unclear"),
        # The known risk: a close-sounding word heard as the challenge word (P-08)
        ("Atro orchard.", "orchard", "approve"),
    ],
)
def test_challenge_word_rule(heard: str, challenge: str, expected: str) -> None:
    assert challenge_word_intent(heard, challenge) == expected


def test_challenge_word_rule_without_a_challenge_is_the_plain_rule() -> None:
    for text in ("yes", "don't do it", "Approved.", ""):
        assert challenge_word_intent(text, None) == intent(text)


def test_carrier_variants() -> None:
    assert with_carrier_variants("Approved Lantern.") == "approve lantern"
    assert with_carrier_variants("A proof lantern") == "approve lantern"
    assert with_carrier_variants("Approve or kid?") == "approve or kid"
