"""The Phase 4 gate's voice runs, guided by voice and checked from the daemon's log.

    uv run python dev/gate_voice.py --home .tools/earwarden --log .tools/earwarden/soak.log

Run it beside
`earwardend --voice --pin-voice --stem --helper … 2>&1 | tee .tools/earwarden/soak.log`,
with the AirPods in. Before each run it tells you what to do, in your AirPods (macOS's `say`, a
different voice from Earwarden's), then starts whatever the run needs and reads the daemon's log
for the outcome. You never need to look at the screen or time anything: do what the voice says.

It prints PASS or FAIL for each run with what the log showed, and writes them to
`<home>/gate-voice.json`. `--only 5,6` runs some of them again. About 8 minutes in all.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIN = Path(sys.executable).parent
PRESS_WAIT_S = 45.0  # how long a run waits for you to press the stem and answer


@dataclass
class Result:
    run: int
    name: str
    passed: bool
    evidence: str


class Log:
    """The daemon's log from a point on."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.offset = path.stat().st_size if path.exists() else 0

    def mark(self) -> None:
        self.offset = self.path.stat().st_size if self.path.exists() else 0

    def lines(self) -> list[str]:
        if not self.path.exists():
            return []
        with self.path.open("r", encoding="utf-8", errors="replace") as file:
            file.seek(self.offset)
            return [line.rstrip("\n") for line in file]

    def wait_for(self, pattern: str, timeout: float) -> re.Match[str] | None:
        found = re.compile(pattern)
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            for line in self.lines():
                if match := found.search(line):
                    return match
            time.sleep(0.25)
        return None

    def count(self, pattern: str) -> int:
        found = re.compile(pattern)
        return sum(1 for line in self.lines() if found.search(line))


def cue(text: str) -> None:
    """An instruction in your ear, in macOS's voice, so it's never mistaken for Earwarden."""
    subprocess.run(["/usr/bin/say", "-r", "185", text], check=False)  # noqa: S603


def earwarden(home: str, *args: str, timeout: float = 120) -> str:
    out = subprocess.run(  # noqa: S603 - our own command
        [str(BIN / "earwarden"), *args, "--home", home],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    return (out.stdout + out.stderr).strip()


def settle(log: Log) -> None:
    """Let the last thing Earwarden said finish before the next cue."""
    time.sleep(2.5)
    log.mark()


def timing(log: Log) -> str:
    """What the log says about the tone, for the evidence."""
    late = log.count(r"the listening tone came")
    early = log.count(r"began before the window")
    stalls = log.count(r"speech stalled")
    return f"tone late {late}, answers begun before the tone {early}, speech stalls {stalls}"


def press_and_say(log: Log, number: int, said: str) -> re.Match[str] | None:
    cue(f"Run {number}. Press the stem once. After the tone, say: {said}.")
    return log.wait_for(r"push-to-talk heard '(.*)': (\w+)", PRESS_WAIT_S)


def run_status(home: str, log: Log) -> Result:
    heard = press_and_say(log, 1, "status")
    ok = heard is not None and heard.group(2) == "status"
    return Result(1, "stem, status", ok, heard.group(0) if heard else "no command heard")


def run_chatty(home: str, log: Log) -> Result:
    heard = press_and_say(log, 2, "chatty mode")
    ok = log.wait_for(r"mode: chatty \(by voice\)", 5) is not None
    return Result(2, "stem, chatty mode", ok, heard.group(0) if heard else "no command heard")


def run_talk(home: str, log: Log) -> Result:
    cue("Run 3. No press this time. After the tone, say: quiet mode.")
    reply = earwarden(home, "talk")
    return Result(3, "earwarden talk, quiet mode", "Quiet mode" in reply, f"reply: {reply!r}")


def run_never_approves(home: str, log: Log) -> Result:
    heard = press_and_say(log, 4, "yes")
    ok = heard is not None and heard.group(2) == "unclear" and log.count(r": allow \(") == 0
    return Result(4, "a command window never approves", ok, heard.group(0) if heard else "none")


def run_tier1(number: int, answer: str, expect: str) -> Callable[[str, Log], Result]:
    def run(home: str, log: Log) -> Result:
        cue(f"Run {number}. A question is coming. After the tone, say: {answer}.")
        out = earwarden(home, "test")
        result = out.splitlines()[-1] if out else ""
        ok = f"Result: {expect}" in result
        return Result(number, f"tier 1, {answer}", ok, f"{result}; {timing(log)}")

    return run


def run_press_during_question(home: str, log: Log) -> Result:
    cue(
        "Run 7. While the next question is being read, press the stem once. "
        "Then, after the tone, say: yes."
    )
    out = earwarden(home, "test")
    result = out.splitlines()[-1] if out else ""
    pressed = log.count(r"button: stem")
    talked = log.count(r"push-to-talk heard")
    ok = "Result: allow" in result and pressed >= 1 and talked == 0
    evidence = f"{result}; presses {pressed}, command windows opened {talked}; {timing(log)}"
    return Result(7, "a press never interrupts an answer window", ok, evidence)


def run_details(home: str, log: Log) -> Result:
    cue("Run 8. Say nothing at all to the next question. I'll tell you when to press.")
    test = subprocess.Popen(  # noqa: S603 - our own command
        [str(BIN / "earwarden"), "test", "--tier", "2", "--home", home],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,  # its hook too, so both end together
    )
    try:
        # The question, then its answer window passes in silence; the request waits, and the
        # floor is free until it's asked again (D-035).
        if log.wait_for(r"heard nothing", 45) is None:
            return Result(8, "details while a request waits", False, "the window didn't pass")
        time.sleep(1)
        cue("Now press the stem. After the tone, say: details.")
        heard = log.wait_for(r"push-to-talk heard '(.*)': (\w+)", 40)
        spelled = heard is not None and heard.group(2) == "details"
        time.sleep(8)  # let it spell the request out
    finally:
        os.killpg(test.pid, signal.SIGTERM)  # as if you answered on the screen
        test.wait(10)
    ended = log.wait_for(r"cancelled \(hook_closed\)", 10) is not None
    evidence = (heard.group(0) if heard else "no command heard") + (
        "; the request was still waiting" if ended else "; the request wasn't waiting"
    )
    return Result(8, "details while a request waits", spelled and ended, evidence)


def run_tier2(home: str, log: Log) -> Result:
    cue("Run 9. A stricter question is coming. After the tone, say approve, and the word it asks.")
    out = earwarden(home, "test", "--tier", "2")
    result = out.splitlines()[-1] if out else ""
    score = log.wait_for(r"voiceprint (\d\.\d+), (\w+)", 1)
    evidence = f"{result}; " + (score.group(0) if score else "no voiceprint score")
    return Result(9, "tier 2, the challenge word", "Result: allow" in result, evidence)


def run_mode(home: str, log: Log) -> Result:
    reply = earwarden(home, "mode", "focus")
    return Result(10, "earwarden mode focus", "Mode: focus" in reply, f"reply: {reply!r}")


RUNS: dict[int, Callable[[str, Log], Result]] = {
    1: run_status,
    2: run_chatty,
    3: run_talk,
    4: run_never_approves,
    5: run_tier1(5, "yes", "allow"),
    6: run_tier1(6, "no", "deny"),
    7: run_press_during_question,
    8: run_details,
    9: run_tier2,
    10: run_mode,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", required=True)
    parser.add_argument("--log", required=True, help="the daemon's log (tee'd from earwardend)")
    parser.add_argument("--only", help="comma-separated run numbers")
    args = parser.parse_args()
    log = Log(Path(args.log))
    started = log.path.read_text(errors="replace") if log.path.exists() else ""
    if "helper connected" not in started or "listening for the stem" not in started:
        print(f"{log.path} shows no daemon with the helper and --stem; start earwardend first.")
        return 1
    chosen = [int(n) for n in args.only.split(",")] if args.only else sorted(RUNS)
    results: list[Result] = []
    cue("Earwarden's voice check. Follow my instructions; each run takes under a minute.")
    for number in chosen:
        settle(log)
        result = RUNS[number](args.home, log)
        results.append(result)
        print(f"run {result.run:2}: {'PASS' if result.passed else 'FAIL'}  {result.name}")
        print(f"         {result.evidence}")
    passed = sum(r.passed for r in results)
    cue(f"Done. {passed} of {len(results)} passed.")
    print(f"\n{passed} of {len(results)} passed")
    out = Path(args.home) / "gate-voice.json"
    out.write_text(json.dumps([r.__dict__ for r in results], indent=2) + "\n", encoding="utf-8")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
