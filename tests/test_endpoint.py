"""The endpointer: one reply in the window, and whether it began before the window (P-20)."""

from __future__ import annotations

from earshot.voice.endpoint import END_SILENCE_S, LEAD_QUIET_S, MAX_SPEECH_S, find_reply

FRAME = 0.02
ROOM = 0.002
VOICE = 0.08


def frames(*spans: tuple[float, float, float]) -> list[tuple[float, float]]:
    """A level per 20 ms frame from (start, end, level) spans, with the room's level between."""
    end = max(stop for _, stop, _ in spans)
    levels = []
    for n in range(round(end / FRAME)):
        t = round(n * FRAME, 2)
        level = next((lv for start, stop, lv in spans if start <= t < stop), ROOM)
        levels.append((t, level))
    return levels


def test_nobody_spoke() -> None:
    assert find_reply(frames((0, 3, ROOM)), opened=1.0, now=3.0) is None


def test_a_reply_after_quiet_ends_after_400_ms_of_quiet() -> None:
    levels = frames((1.6, 2.0, VOICE), (2.0, 3.0, ROOM))
    reply = find_reply(levels, opened=1.0, now=3.0)
    assert reply is not None
    assert (reply.start, reply.end, reply.cut_off) == (1.6, 1.98, False)
    assert reply.threshold == 0.01  # the room is quiet, so the floor applies
    assert reply.loudest == VOICE


def test_a_reply_is_still_going_until_the_quiet_is_long_enough() -> None:
    levels = frames((1.6, 2.0, VOICE), (2.0, 2.3, ROOM))
    reply = find_reply(levels, opened=1.0, now=2.3)
    assert reply is not None
    assert reply.end is None
    assert END_SILENCE_S > 2.3 - 1.98


def test_a_short_pause_doesnt_end_a_reply() -> None:
    levels = frames((1.4, 1.7, VOICE), (1.9, 2.2, VOICE), (2.2, 3.0, ROOM))  # "no, ... stop"
    reply = find_reply(levels, opened=1.0, now=3.0)
    assert reply is not None
    assert reply.end == 2.18


def test_a_reply_ends_at_six_seconds() -> None:
    levels = frames((1.0, 9.0, VOICE), (9.0, 9.2, ROOM))
    reply = find_reply(levels, opened=0.9, now=9.2)
    assert reply is not None
    assert reply.end is not None
    assert reply.end - reply.start < MAX_SPEECH_S


def test_a_reply_under_way_when_the_window_opens_is_cut_off() -> None:
    """You talked over the prompt: the window opens on the tail of "don't do it"."""
    levels = frames((0.6, 1.5, VOICE), (1.5, 2.5, ROOM))
    reply = find_reply(levels, opened=1.0, now=2.5)
    assert reply is not None
    assert reply.start >= 1.0  # what came before the window is never part of the reply (D-015)
    assert reply.cut_off


def test_a_pause_inside_a_reply_still_counts_as_cut_off() -> None:
    """The window opens in the gap between "don't" and "do it"."""
    levels = frames((0.5, 0.95, VOICE), (1.1, 1.5, VOICE), (1.5, 2.5, ROOM))
    reply = find_reply(levels, opened=1.0, now=2.5)
    assert reply is not None
    assert LEAD_QUIET_S > 1.1 - 0.94
    assert reply.cut_off


def test_a_reply_after_a_comma_pause_is_cut_off() -> None:
    """Step 0's "deploy, yes": 0.38 s between the words, and the window opened between them."""
    levels = frames((0.92, 1.38, VOICE), (1.76, 2.08, VOICE), (2.08, 3.0, ROOM))
    reply = find_reply(levels, opened=1.45, now=3.0)
    assert reply is not None
    assert reply.start == 1.76
    assert reply.cut_off


def test_sound_well_before_the_window_doesnt_cut_off_a_reply() -> None:
    levels = frames((0.2, 0.5, VOICE), (1.4, 1.8, VOICE), (1.8, 2.5, ROOM))
    reply = find_reply(levels, opened=1.0, now=2.5)
    assert reply is not None
    assert not reply.cut_off


def test_an_ignored_noise_inside_the_window_doesnt_cut_off_what_follows() -> None:
    """A bump at 1.2 s, judged not speech, with a soft tail; the search starts again after it.
    The room is quieter there, so the threshold drops and the tail becomes a "reply" right after
    the bump. The bump was inside the window, so it mustn't make that "begin before the window"
    (at the Phase 4 gate, a noise became "Wait for the tone" with nobody speaking)."""
    levels = frames((0.0, 1.2, 0.004), (1.2, 1.3, VOICE), (1.3, 1.5, 0.015), (1.5, 3.0, 0.003))
    after_bump = 1.31
    old = find_reply(levels, opened=after_bump, now=3.0)
    assert old is not None
    assert old.cut_off  # what it used to say
    reply = find_reply(levels, opened=after_bump, now=3.0, window=1.0)
    assert reply is not None
    assert not reply.cut_off


def test_sound_before_the_real_window_still_cuts_off_a_reply_found_later() -> None:
    """Talking over the prompt is caught however late the search starts."""
    levels = frames((0.6, 1.2, VOICE), (1.2, 2.5, ROOM))
    reply = find_reply(levels, opened=1.0, now=2.5, window=1.0)
    assert reply is not None
    assert reply.cut_off
