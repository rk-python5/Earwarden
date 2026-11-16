"""Push-to-talk commands: the spec's words, and nothing that could approve (Phase 4)."""

from __future__ import annotations

import pytest

from earshot.voice import commands, intents


@pytest.mark.parametrize(
    ("said", "kind", "mode"),
    [
        ("Status.", "status", None),
        ("What's everyone doing?", "status", None),
        ("Earshot, what's everyone doing", "status", None),
        ("Repeat.", "repeat", None),
        ("Say that again, please.", "repeat", None),
        ("Details.", "details", None),
        ("Spell it out.", "details", None),
        ("Stop.", "stop", None),
        ("Be quiet.", "stop", None),
        ("Quiet mode.", "mode", "quiet"),
        ("Earshot, quiet mode.", "mode", "quiet"),
        ("Focus.", "mode", "focus"),
        ("Chatty mode please", "mode", "chatty"),
    ],
)
def test_the_spec_commands_are_understood(said: str, kind: str, mode: str | None) -> None:
    assert commands.parse(said) == commands.Command(kind, mode)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "said",
    [
        "Yes.",
        "No.",
        "Approve.",
        "Go ahead.",
        "Approve harbor.",
        "Yes, status.",
        "",
        "Mmm.",
        "Allow it",
    ],
)
def test_nothing_in_a_command_window_approves_or_denies(said: str) -> None:
    assert commands.parse(said).kind == "unclear"


def test_every_approval_and_denial_word_is_unclear_as_a_command() -> None:
    # "stop" is both a denial and the silence command, and that's fine: as a command it only
    # silences announcements, and the window never reaches a waiting request.
    for word in intents.APPROVE | intents.WAIT | (intents.DENY - {"stop"}):
        assert commands.parse(word).kind == "unclear", word
