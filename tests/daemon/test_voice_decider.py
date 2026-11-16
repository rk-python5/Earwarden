"""The voice decider with a scripted voice: what it says, what it hears, and what it decides."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Literal

import pytest
from conftest import StartDaemon
from harness import finish, fixture, run_hook, start_hook

from earshot import contracts, wire
from earshot.daemon.state import Pending, Sessions
from earshot.voice import challenge
from earshot.voice.decider import CUT_OFF, NOD, SHAKE, Heard, Speaker, VoiceDecider

TOO_EARLY = Heard("", CUT_OFF, 0)  # an answer begun before the listening tone


class FakeVoice:
    def __init__(
        self, answers: list[str | Heard | None], headset: bool = True, enrolled: bool = False
    ) -> None:
        self.answers: Iterator[str | Heard | None] = iter(answers)
        self.headset = headset
        self.enrolled = enrolled
        self.said: list[str] = []
        self.mic_open = False
        self.listens = 0

    def headset_ready(self) -> bool:
        return self.headset

    def speaker_ready(self) -> bool:
        return self.enrolled

    def can_say(self, word: str) -> bool:
        return word.lower() != "pydantic"

    async def say(self, text: str, chime: int | None = None) -> None:
        self.said.append(text)

    async def listen(self, seconds: float) -> Heard | None:
        self.listens += 1
        answer = next(self.answers, None)
        if answer is None or isinstance(answer, Heard):
            return answer
        return Heard(answer, "parakeet", 70)

    async def open_mic(self) -> None:
        self.mic_open = True

    async def close_mic(self) -> None:
        self.mic_open = False


class Away:
    def __init__(self, away: bool = True) -> None:
        self.value = away

    def away(self) -> bool:
        return self.value


EDIT = {"file_path": "/Users/rehaan/code/api/src/app.py", "old_string": "a", "new_string": "b"}


def pending(tool: str = "Edit", tool_input: dict[str, Any] | None = None) -> Pending:
    fields = {
        "v": 1,
        "id": wire.new_request_id(),
        "token": "ab" * 32,
        "source": "claude_code",
        "session_id": "s1",
        "cwd": "/Users/rehaan/code/api",
        "permission_mode": "default",
        "tool_name": tool,
        "tool_input": tool_input or EDIT,
        "received_at": wire.utc_timestamp(),
    }
    request = contracts.ApprovalRequest.model_validate_json(wire.encode(fields))
    session = Sessions().seen("s1", "/Users/rehaan/code/api")
    return Pending(request, wire.input_sha256(request.tool_input), session)


def decide(voice: FakeVoice, item: Pending, away: bool = True) -> contracts.Decision:
    decider = VoiceDecider(voice, Away(away), reannounce_s=0, reannounce_max=2)
    return asyncio.run(decider(item))


def test_yes_approves_an_edit() -> None:
    voice, item = FakeVoice(["Yes."]), pending()
    assert decide(voice, item).outcome == "allow"
    assert voice.said == ["api wants to edit app dot p y, in the src folder. Approve?"]
    assert item.notes["transcript"] == "Yes."
    assert item.notes["tier"] == 1
    assert not voice.mic_open


def test_no_denies_and_an_instruction_reaches_the_agent() -> None:
    assert decide(FakeVoice(["no"]), pending()).outcome == "deny"
    answer = decide(FakeVoice(["No, use poetry instead."]), pending())
    assert (answer.outcome, answer.message) == ("deny", "use poetry instead.")


def test_wait_hands_off() -> None:
    voice = FakeVoice(["hold on"])
    assert decide(voice, pending()).outcome == "handoff"
    assert voice.said[-1] == "Okay, it's on your screen."


def test_one_unclear_answer_is_asked_again() -> None:
    voice = FakeVoice(["mm-hmm", "yes"])
    assert decide(voice, pending()).outcome == "allow"
    assert "Sorry, say yes or no." in voice.said


def test_an_answer_begun_too_early_is_asked_again_after_the_tone() -> None:
    voice = FakeVoice([TOO_EARLY, "no"])
    assert decide(voice, pending()).outcome == "deny"
    assert "Wait for the tone, then say yes or no." in voice.said
    assert "Sorry, say yes or no." not in voice.said


def test_two_answers_begun_too_early_go_to_the_screen() -> None:
    voice = FakeVoice([TOO_EARLY, TOO_EARLY])
    assert decide(voice, pending()).outcome == "handoff"


INSTALL = {"command": "pip install httpx"}  # tier 2: the built-in install rule


def tier_two(
    monkeypatch: pytest.MonkeyPatch, answers: list[str | Heard | None], enrolled: bool = True
) -> tuple[FakeVoice, contracts.Decision, Pending]:
    monkeypatch.setattr(challenge, "pick", lambda: "harbor")
    voice = FakeVoice(answers, enrolled=enrolled)
    item = pending("Bash", INSTALL)
    return voice, decide(voice, item), item


def you(text: str, verdict: Literal["match", "borderline", "mismatch"] = "match") -> Heard:
    return Heard(text, "parakeet", 70, Speaker(0.71, verdict))


def test_tier_2_asks_for_the_challenge_word(monkeypatch: pytest.MonkeyPatch) -> None:
    voice, decision, item = tier_two(monkeypatch, [you("approve harbor")])
    assert decision.outcome == "allow"
    assert voice.said[0].endswith("To install, say: approve harbor.")
    assert (item.notes["challenge"], item.notes["voiceprint"]) == ("harbor", 0.71)


def test_a_plain_yes_never_answers_a_challenge(monkeypatch: pytest.MonkeyPatch) -> None:
    voice, decision, _ = tier_two(monkeypatch, [you("yes"), you("Approve harbor.")])
    assert decision.outcome == "allow"
    assert "Sorry, say: approve harbor." in voice.said


def test_the_right_word_in_the_wrong_voice_goes_to_the_screen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for verdict in ("borderline", "mismatch"):
        voice, decision, item = tier_two(monkeypatch, [you("approve harbor", verdict)])
        assert decision.outcome == "handoff"
        assert voice.said[-1] == "Didn't catch that clearly; it's on your screen."
        assert f"voiceprint: {verdict}" in item.notes["rules"]


def test_a_challenge_without_a_voiceprint_result_goes_to_the_screen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, decision, _ = tier_two(monkeypatch, ["approve harbor"])
    assert decision.outcome == "handoff"


def test_no_still_denies_at_tier_2(monkeypatch: pytest.MonkeyPatch) -> None:
    _, decision, _ = tier_two(monkeypatch, [you("no")])
    assert decision.outcome == "deny"


def test_tier_2_waits_for_an_enrolled_voiceprint(monkeypatch: pytest.MonkeyPatch) -> None:
    voice, decision, item = tier_two(monkeypatch, [you("approve harbor")], enrolled=False)
    assert decision.outcome == "handoff"
    assert voice.said[-1].endswith("It's on your screen.")
    assert "voice: tier 2 waits for an enrolled voiceprint" in item.notes["rules"]


def test_a_shake_hands_off_and_never_denies() -> None:
    voice = FakeVoice([Heard("", SHAKE, 0)])
    item = pending()
    assert decide(voice, item).outcome == "handoff"
    assert voice.said[-1] == "Okay, it's on your screen."
    assert item.notes["gesture"] == "shake"


def test_a_nod_approves_tier_1_only(monkeypatch: pytest.MonkeyPatch) -> None:
    item = pending()
    assert decide(FakeVoice([Heard("", NOD, 0)]), item).outcome == "allow"
    assert item.notes["gesture"] == "nod"
    voice, decision, _ = tier_two(monkeypatch, [Heard("", NOD, 0), Heard("", NOD, 0)])
    assert decision.outcome == "handoff"  # a nod never answers a challenge
    assert "Sorry, say: approve harbor." in voice.said


def test_two_unclear_answers_go_to_the_screen() -> None:
    voice = FakeVoice(["okay", "sure"])
    assert decide(voice, pending()).outcome == "handoff"


def test_silence_is_announced_again_then_handed_off() -> None:
    voice = FakeVoice([None, None, "yes"])
    assert decide(voice, pending()).outcome == "allow"
    assert voice.said.count(voice.said[0]) == 3  # asked, then asked twice more (D-020)
    assert decide(FakeVoice([None, None, None, None]), pending()).outcome == "handoff"


def test_an_approval_that_outlives_its_window_is_announced(monkeypatch: pytest.MonkeyPatch) -> None:
    from earshot.daemon.floor import FAILURE

    async def scenario() -> None:
        voice = FakeVoice([None, None, None, None])
        decider = VoiceDecider(voice, Away(), reannounce_s=0, reannounce_max=2)
        assert (await decider(pending())).outcome == "handoff"
        (waiting,) = decider.floor._waiting
        assert (waiting.priority, waiting.text) == (FAILURE, "api approval moved to your screen.")
        assert await decider.floor.pump()  # said once the floor is free
        assert voice.said[-1] == "api approval moved to your screen."
        assert decider.floor.last_said == voice.said[-1]

    asyncio.run(scenario())


def test_at_the_keyboard_nothing_is_said() -> None:
    voice = FakeVoice(["yes"])
    item = pending()
    assert decide(voice, item, away=False).outcome == "handoff"
    assert voice.said == []
    assert "presence: at the keyboard" in item.notes["rules"]


def test_without_the_headset_nothing_is_said() -> None:
    voice = FakeVoice(["yes"], headset=False)
    assert decide(voice, pending()).outcome == "handoff"
    assert voice.said == []


def test_what_voice_may_not_approve_is_only_announced() -> None:
    voice = FakeVoice(["yes"])
    item = pending("Bash", {"command": "git push --force origin main"})
    assert decide(voice, item).outcome == "handoff"
    assert voice.said == ["api wants to push main to origin, as a force push. It's on your screen."]
    assert voice.listens == 0
    assert item.notes["tier"] == 3


def test_unsayable_words_are_spelled_out() -> None:
    voice = FakeVoice(["yes"])
    decide(voice, pending("Bash", {"command": "pytest pydantic"}))
    assert "P Y D A N T I C" not in voice.said[0]  # a test run is said as "run the tests"
    voice = FakeVoice(["no"])
    decide(voice, pending("Write", {"file_path": "/Users/rehaan/code/api/pydantic.txt"}))
    assert "P Y D A N T I C dot t x t" in voice.said[0]


def test_one_approval_at_a_time() -> None:
    async def both() -> tuple[contracts.Decision, contracts.Decision]:
        voice = FakeVoice(["yes", "no"])
        decider = VoiceDecider(voice, Away(), reannounce_s=0)
        first, second = await asyncio.gather(decider(pending()), decider(pending()))
        assert voice.said[1].endswith("Approve?")  # the second asked only after the first
        return first, second

    first, second = asyncio.run(both())
    assert (first.outcome, second.outcome) == ("allow", "deny")


def test_the_whole_path_with_the_real_hook(home: Path, start_daemon: StartDaemon) -> None:
    voice = FakeVoice(["yes"])
    start_daemon(VoiceDecider(voice, Away(), reannounce_s=0))
    request = fixture("permission_request")
    request["tool_name"] = "Edit"
    request["tool_input"] = {
        "file_path": f"{request['cwd']}/notes.md",
        "old_string": "a",
        "new_string": "b",
    }
    printed = json.loads(run_hook(home, request))
    assert printed["hookSpecificOutput"]["decision"] == {"behavior": "allow"}


def test_approving_on_screen_silences_a_waiting_question(
    home: Path, start_daemon: StartDaemon
) -> None:
    class Hesitant(FakeVoice):
        async def listen(self, seconds: float) -> Heard | None:
            await asyncio.sleep(30)
            return None

    voice = Hesitant([])
    running = start_daemon(VoiceDecider(voice, Away(), reannounce_s=0))
    waiting = start_hook(
        home,
        fixture("permission_request")
        | {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "/Users/rehaan/earshot-probe/a.txt",
                "old_string": "a",
                "new_string": "b",
            },
        },
    )
    running.wait_for(lambda d: len(d.pending) == 1)
    tool_ran = fixture("post_tool_use") | {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": "/Users/rehaan/earshot-probe/a.txt",
            "old_string": "a",
            "new_string": "b",
        },
    }
    run_hook(home, tool_ran, "--event")
    assert finish(waiting) == b""
    assert running.daemon.resolved[-1].reason == "tool_ran"
    running.wait_for(lambda d: not voice.mic_open)


@pytest.mark.parametrize("answer", ["yes", "no"])
def test_decisions_are_audited_with_what_was_heard(answer: str) -> None:
    item = pending()
    decide(FakeVoice([answer]), item)
    assert item.notes["recognizer"] == "parakeet"
    assert item.notes["timings_ms"]["recognize"] == 70


def test_the_decider_says_why_the_risk_gate_raised_a_request() -> None:
    class Scoring:
        def score(self, tool_name: str, tool_input: dict[str, Any], cwd: str) -> Any:
            return contracts.GateScore(score=0.6, reasons=("secrets_nearby",))

    voice, item = FakeVoice(["yes"]), pending()
    decider = VoiceDecider(voice, Away(), gate=Scoring())
    answer = asyncio.run(decider(item))
    assert answer.outcome == "handoff"  # raised to tier 2, and no voiceprint: the screen
    assert item.notes["tier"] == 2
    assert "gate: 0.60, secrets nearby: tier 1 raised to 2" in item.notes["rules"]
    assert voice.said == [
        "api wants to edit app dot p y, in the src folder. Raised, for secrets nearby. "
        "It's on your screen."
    ]
