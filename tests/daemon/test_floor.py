"""The floor manager: who speaks when, modes, batching and the gap (Phase 4, milestone 2)."""

from __future__ import annotations

import asyncio

import pytest

from earshot.daemon import floor as floor_module
from earshot.daemon.floor import FAILURE, FINISHED, PROGRESS, Floor


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


class Voice:
    def __init__(self, headset: bool = True) -> None:
        self.said: list[str] = []
        self.headset = headset

    def headset_ready(self) -> bool:
        return self.headset

    async def say(self, text: str, chime: int | None = None) -> None:
        self.said.append(text)


class Presence:
    def __init__(self, away: bool = True) -> None:
        self.value = away

    def away(self) -> bool:
        return self.value


def make(
    mode: str = "focus", away: bool = True, headset: bool = True
) -> tuple[Floor, Voice, Clock]:
    clock, voice = Clock(), Voice(headset)
    made = Floor(voice, Presence(away), now=clock)
    made.mode = mode  # type: ignore[assignment]
    return made, voice, clock


def pump(made: Floor) -> bool:
    return asyncio.run(made.pump())


def test_a_failure_is_announced_when_the_floor_is_free() -> None:
    made, voice, _ = make()
    made.announce(FAILURE, "docs approval moved to your screen.")
    assert pump(made)
    assert voice.said == ["docs approval moved to your screen."]
    assert made.last_said == voice.said[0]
    assert not pump(made)  # nothing left


def test_failures_come_before_finishes_and_older_first() -> None:
    made, voice, clock = make("chatty")
    made.finished("api")
    clock.t += 11  # past the batch window, so it's due
    made.announce(FAILURE, "second failure.")
    made.announce(FAILURE, "third failure.")
    made._waiting[1].at -= 5  # the second one queued earlier
    pump(made)
    assert voice.said == ["second failure."]


def test_at_most_one_unrequested_announcement_every_20_seconds() -> None:
    made, voice, clock = make()
    made.announce(FAILURE, "one.")
    made.announce(FAILURE, "two.")
    assert pump(made)
    assert not pump(made)
    clock.t += 19
    assert not pump(made)
    clock.t += 1
    assert pump(made)
    assert voice.said == ["one.", "two."]


def test_finishes_within_10_seconds_are_said_together() -> None:
    made, voice, clock = make("chatty")
    made.finished("api")
    clock.t += 4
    made.finished("docs")
    clock.t += 3
    made.finished("deploy")
    made.finished("docs")  # again: not repeated
    assert not pump(made)  # the batch is still open
    clock.t += 4
    assert pump(made)
    assert voice.said == ["api, docs and deploy finished."]


def test_a_finish_long_after_the_last_starts_a_new_batch() -> None:
    made, voice, clock = make("chatty")
    made.finished("api")
    clock.t += 11
    made.finished("docs")
    assert pump(made)
    clock.t += 20
    assert pump(made)
    assert voice.said == ["api finished.", "docs finished."]


def test_an_announcement_that_waited_two_minutes_is_dropped() -> None:
    made, voice, clock = make()
    made.announce(FAILURE, "old news.")
    clock.t += floor_module.STALE_S + 1
    assert not pump(made)
    assert voice.said == []


@pytest.mark.parametrize(
    ("mode", "said"),
    [
        ("quiet", []),
        ("focus", ["a failure."]),
        ("chatty", ["a failure.", "api finished."]),
    ],
)
def test_each_mode_lets_through_what_it_should(mode: str, said: list[str]) -> None:
    made, voice, clock = make(mode)
    made.announce(FAILURE, "a failure.")
    made.finished("api")
    clock.t += 11
    for _ in range(3):
        pump(made)
        clock.t += 21
    assert voice.said == said


def test_chatty_mode_briefs_every_five_minutes_while_something_runs() -> None:
    made, voice, clock = make("chatty")
    running = ["Two sessions. api: running 3 minutes, 4 tools run. docs: idle."]
    made.briefing = lambda: running[0] if running else None
    assert pump(made)  # the first briefing comes at once
    assert voice.said == running
    clock.t += 200
    assert not pump(made)
    clock.t += 100
    assert pump(made)
    assert len(voice.said) == 2
    running.clear()  # nothing running: no briefing
    clock.t += 300
    assert not pump(made)
    made.mode = "focus"
    running.append("Two sessions.")
    clock.t += 300
    assert not pump(made)  # only chatty mode briefs on its own


def test_an_announcement_never_interrupts_an_open_approval() -> None:
    async def scenario() -> None:
        made, voice, _ = make()
        made.announce(FAILURE, "a failure.")
        async with made.approval():
            assert made.queued == 0
            assert not await made.pump()  # the floor is taken: wait
            assert voice.said == []
        assert await made.pump()
        assert voice.said == ["a failure."]

    asyncio.run(scenario())


def test_approvals_count_the_ones_waiting() -> None:
    async def scenario() -> None:
        made, _, _ = make()
        seen: list[int] = []

        async def one() -> None:
            async with made.approval():
                seen.append(made.queued)
                await asyncio.sleep(0.01)

        await asyncio.gather(one(), one(), one())
        # The first took the floor before the others arrived; the second saw the third waiting.
        assert seen == [0, 1, 0]

    asyncio.run(scenario())


def test_at_the_keyboard_or_without_the_headset_nothing_is_announced() -> None:
    for away, headset in ((False, True), (True, False)):
        made, voice, _ = make(away=away, headset=headset)
        made.announce(FAILURE, "a failure.")
        assert not pump(made)
        assert voice.said == []
        assert made._waiting == []  # dropped, not kept for later
        assert not asyncio.run(made.say("a briefing"))


def test_requested_speech_ignores_the_gap_and_is_remembered() -> None:
    made, voice, _ = make()
    made.announce(FAILURE, "a failure.")
    pump(made)
    assert asyncio.run(made.say("Two sessions."))
    assert voice.said == ["a failure.", "Two sessions."]
    assert made.last_said == "Two sessions."


def test_progress_is_never_announced_outside_a_briefing() -> None:
    made, _, clock = make("chatty")
    made.announce(PROGRESS, "api ran a tool.")
    clock.t += 1
    assert pump(made)  # queued progress is allowed in chatty mode when something queues it...
    made2, voice2, _ = make("focus")
    made2.announce(PROGRESS, "api ran a tool.")
    assert not pump(made2)  # ...but focus and quiet drop it
    assert voice2.said == []


def test_the_background_task_says_what_is_queued() -> None:
    async def scenario() -> None:
        made, voice, _ = make()
        made.start()
        made.announce(FAILURE, "a failure.")
        for _ in range(100):
            if voice.said:
                break
            await asyncio.sleep(0.02)
        await made.stop()
        assert voice.said == ["a failure."]
        assert made.finished is not None  # still usable after stop

    asyncio.run(scenario())


def test_a_mode_change_drops_what_the_new_mode_forbids() -> None:
    made, voice, clock = make("chatty")
    made.finished("api")
    made.mode = "quiet"
    clock.t += 11
    assert not pump(made)
    assert made._waiting == []
    assert voice.said == []


def test_joining_names() -> None:
    assert floor_module._join(["api"]) == "api"
    assert floor_module._join(["api", "docs"]) == "api and docs"
    assert floor_module._join(["api", "docs", "deploy"]) == "api, docs and deploy"
    assert FINISHED > FAILURE
