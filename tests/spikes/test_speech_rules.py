"""The speech spike's labels match its intent rules, and only real approvals approve."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "spikes" / "speech"))

from speech_data import CHALLENGE_WORDS, REPLIES, intent, normalize


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
