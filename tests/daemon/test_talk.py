"""Push-to-talk: one command window that can never answer a request (Phase 4, milestone 3)."""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from conftest import StartDaemon
from harness import finish, fixture, never, start_hook

from earwarden import wire
from earwarden.daemon.floor import FAILURE, Floor
from earwarden.voice.decider import SHAKE, Heard


class Voice:
    """The floor's speaker and the daemon's listener in one, scripted."""

    def __init__(self, answers: list[str | Heard | None], headset: bool = True) -> None:
        self.answers: Iterator[str | Heard | None] = iter(answers)
        self.headset = headset
        self.said: list[str] = []
        self.mic: list[str] = []

    def headset_ready(self) -> bool:
        return self.headset

    async def say(self, text: str, chime: int | None = None, tone: bool = False) -> None:
        self.said.append(text)

    async def open_mic(self) -> None:
        self.mic.append("open")

    async def close_mic(self) -> None:
        self.mic.append("close")

    async def listen(self, seconds: float) -> Heard | None:
        answer = next(self.answers, None)
        if answer is None or isinstance(answer, Heard):
            return answer
        return Heard(answer, "parakeet", 50)


class Away:
    def __init__(self, away: bool = True) -> None:
        self.value = away

    def away(self) -> bool:
        return self.value


def talk(home: Path) -> dict[str, Any]:
    from test_daemon import raw_exchange, token

    message = {"v": 1, "token": token(home), "source": "python_api", "command": "talk"}
    reply: dict[str, Any] = json.loads(raw_exchange(home, wire.encode(message)))
    return reply


def started(start_daemon: StartDaemon, answers: list[Any], away: bool = True) -> tuple[Any, Voice]:
    voice = Voice(answers)
    floor = Floor(voice, Away(away))
    return start_daemon(decider=never, floor=floor, listener=voice), voice


def test_status_by_voice_says_the_briefing(home: Path, start_daemon: StartDaemon) -> None:
    running, voice = started(start_daemon, ["What's everyone doing?"])
    reply = talk(home)
    assert reply["ok"] is True
    assert reply["text"] == "No sessions are open."
    assert voice.said == ["No sessions are open."]
    assert voice.mic == ["open", "close"]
    assert running.daemon.floor.last_said == "No sessions are open."


def test_modes_and_stop_by_voice(home: Path, start_daemon: StartDaemon) -> None:
    running, voice = started(start_daemon, ["Earwarden, chatty mode.", "Stop.", "Repeat."])
    floor = running.daemon.floor
    assert talk(home)["text"] == "Chatty mode."
    assert floor.mode == "chatty"
    floor.announce(FAILURE, "something waiting.")
    assert talk(home)["text"] == "Okay, quiet."
    assert floor._waiting == []
    assert talk(home)["text"] == "Okay, quiet."  # repeat says the last thing, and isn't itself kept
    assert voice.said == ["Chatty mode.", "Okay, quiet.", "Okay, quiet."]


def test_nothing_said_in_the_window_approves_a_waiting_request(
    home: Path, start_daemon: StartDaemon
) -> None:
    running, _ = started(start_daemon, ["Yes.", "Approve.", "Go ahead."])
    proc = start_hook(home, fixture("permission_request"))
    try:
        running.wait_for(lambda d: len(d.pending) == 1)
        for _ in range(3):
            reply = talk(home)
            assert reply["ok"] is False
            assert reply["text"] == "Sorry, I didn't catch that."
        assert len(running.daemon.pending) == 1  # still waiting, untouched
        assert all(p.notes == {} for p in running.daemon.pending.all())
    finally:
        proc.terminate()
        finish(proc)


def test_details_spells_out_the_waiting_request(home: Path, start_daemon: StartDaemon) -> None:
    running, _ = started(start_daemon, ["Details.", "Details."])
    assert talk(home)["text"] == "Nothing is waiting."
    proc = start_hook(home, fixture("permission_request"))
    try:
        running.wait_for(lambda d: len(d.pending) == 1)
        text = talk(home)["text"]
        assert "wants to" in text
        assert ": " in text  # a critical field, letter by letter
        assert " T " in text.upper()
        assert len(running.daemon.pending) == 1
    finally:
        proc.terminate()
        finish(proc)


def test_a_shake_cancels_and_silence_or_an_early_start_is_unclear(
    home: Path, start_daemon: StartDaemon
) -> None:
    _, voice = started(start_daemon, [Heard("", SHAKE, 0), None, Heard("", "cut off", 0)])
    assert talk(home) == {"v": 1, "ok": True, "text": "Okay."}
    assert talk(home)["text"] == "Sorry, I didn't catch that."
    assert talk(home)["text"] == "Sorry, I didn't catch that."
    assert voice.said == ["Sorry, I didn't catch that."] * 2  # a shake says nothing


def test_the_window_never_opens_over_an_approval(home: Path, start_daemon: StartDaemon) -> None:
    import asyncio

    running, voice = started(start_daemon, ["Status."])
    floor = running.daemon.floor
    taken = asyncio.run_coroutine_threadsafe(floor.lock.acquire(), running.daemon._loop)
    taken.result(timeout=5)
    reply = talk(home)
    assert reply["ok"] is False
    assert "approval is open" in reply["text"]
    assert voice.mic == []
    running.daemon._loop.call_soon_threadsafe(floor.lock.release)


def test_at_the_keyboard_the_window_doesnt_open(home: Path, start_daemon: StartDaemon) -> None:
    _, voice = started(start_daemon, ["Status."], away=False)
    assert talk(home)["ok"] is False
    assert voice.mic == []


def test_a_stem_press_opens_the_window(home: Path, start_daemon: StartDaemon) -> None:
    running, voice = started(start_daemon, ["Focus mode."])
    running.daemon._loop.call_soon_threadsafe(running.daemon.press)
    running.wait_for(lambda d: bool(voice.said))
    assert voice.said == ["Focus mode."]


def test_a_burst_of_presses_opens_one_window(home: Path, start_daemon: StartDaemon) -> None:
    running, voice = started(start_daemon, ["Focus mode.", "Chatty mode."])

    def burst() -> None:
        for _ in range(1000):  # what a looping helper sent at the gate, in miniature
            running.daemon.press()

    running.daemon._loop.call_soon_threadsafe(burst)
    running.wait_for(lambda d: bool(voice.said))
    time.sleep(0.2)
    assert voice.said == ["Focus mode."]
    assert voice.mic == ["open", "close"]
