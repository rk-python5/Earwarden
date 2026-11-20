"""Answer rules (D-024): only exact approvals approve; session names are never parsed."""

from __future__ import annotations

import pytest

from earwarden.voice.intents import Intent, parse


@pytest.mark.parametrize(
    ("said", "intent"),
    [
        ("Yes.", Intent("approve")),
        ("yeah", Intent("approve")),
        ("Go ahead", Intent("approve")),
        ("do it", Intent("approve")),
        ("No.", Intent("deny")),
        ("Stop!", Intent("deny")),
        ("no, don't", Intent("deny")),
        ("don't do it", Intent("deny")),
        ("don't approve that", Intent("deny")),
        ("No, use poetry instead.", Intent("instruction", "use poetry instead.")),
        ("Yes, but run the tests first", Intent("instruction", "Yes, but run the tests first")),
        ("wait", Intent("wait")),
        ("do it later", Intent("wait")),
        ("not yet", Intent("wait")),
        ("API, yes", Intent("unclear")),
        ("okay", Intent("unclear")),
        ("Mm-hmm.", Intent("unclear")),
        ("", Intent("unclear")),
        ("yes yes", Intent("unclear")),
    ],
)
def test_answers(said: str, intent: Intent) -> None:
    assert parse(said) == intent
