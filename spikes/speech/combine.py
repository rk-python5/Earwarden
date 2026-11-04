# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Two-stage recognition, worked out from two finished asr_eval.py runs. No models run here.

    uv run spikes/speech/combine.py parakeet-tdt-0.6b-v2 whisper-large-v3-turbo-asr-fp16
    uv run spikes/speech/combine.py moonshine-base whisper-large-v3-turbo-asr-fp16

The first recogniser hears every reply. Only when its answer is unclear, an empty transcript
included, does the second one get a listen. Each transcript is judged with the rules Earshot would
use: the whole reply must match (P-07), and for a challenge phrase the challenge word alone decides
(P-08, revised). Reads out/asr_results-<model>-trim.csv for both; --untrimmed reads the 3-second
runs instead. Standard library only.
"""

from __future__ import annotations

import argparse
import csv
import statistics
import sys
from pathlib import Path
from typing import NamedTuple

from speech_data import challenge_word_intent

OUT = Path(__file__).resolve().parent / "out"


class Outcome(NamedTuple):
    condition: str
    said: str
    wanted: str
    got: str
    challenge: bool
    second_listen: bool
    latency_ms: float
    heard: str


def load(directory: Path, tag: str, trimmed: bool) -> dict[tuple[str, str], dict[str, str]]:
    path = directory / f"asr_results-{tag}{'-trim' if trimmed else ''}.csv"
    if not path.exists():
        sys.exit(f"No {path}. Run asr_eval.py{' --trim' if trimmed else ''} with that model first.")
    with path.open(newline="", encoding="utf-8") as f:
        return {(row["condition"], row["id"]): row for row in csv.DictReader(f)}


def decide(row: dict[str, str]) -> str:
    return challenge_word_intent(row["transcript"], row["challenge"] or None)


def outcomes(
    first: dict[tuple[str, str], dict[str, str]],
    second: dict[tuple[str, str], dict[str, str]] | None,
) -> list[Outcome]:
    """Decide every reply with the first recogniser, falling back to the second when unclear."""
    results = []
    for key in sorted(first if second is None else first.keys() & second.keys()):
        row = first[key]
        got, heard = decide(row), row["transcript"]
        latency = float(row["latency_ms"])
        fallback = second is not None and got == "unclear"
        if fallback and second is not None:
            backup = second[key]
            got, heard = decide(backup), f"{heard!r} → {backup['transcript']!r}"
            latency += float(backup["latency_ms"])
        results.append(
            Outcome(
                condition=row["condition"],
                said=row["text"],
                wanted=row["intent"],
                got=got,
                challenge=bool(row["challenge"]),
                second_listen=fallback,
                latency_ms=latency,
                heard=heard,
            )
        )
    return results


def p95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(0.95 * (len(ordered) - 1)))]


def report(name: str, results: list[Outcome]) -> None:
    print(f"\n{name}")
    for condition in sorted({o.condition for o in results}):
        group = [o for o in results if o.condition == condition]
        yes_no = [o for o in group if o.wanted in {"approve", "deny"} and not o.challenge]
        right = sum(o.got == o.wanted for o in yes_no)
        intents = sum(o.got == o.wanted for o in group)
        false = sum(o.got == "approve" and o.wanted != "approve" for o in group)
        missed = sum(o.wanted == "approve" and o.got != "approve" for o in group)
        print(
            f"  {condition:6} yes/no {right}/{len(yes_no)} ({right / len(yes_no):.1%})  "
            f"intent {intents}/{len(group)}  false approvals {false}  approvals missed {missed}"
        )
    times = [o.latency_ms for o in results]
    listens = sum(o.second_listen for o in results)
    print(
        f"  second listen on {listens}/{len(results)} replies; time per reply: median "
        f"{statistics.median(times):.0f} ms, p95 {p95(times):.0f} ms, max {max(times):.0f} ms"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("first", help="model tag that hears every reply, e.g. parakeet-tdt-0.6b-v2")
    parser.add_argument("second", help="model tag for a second listen when the first is unclear")
    parser.add_argument("--untrimmed", action="store_true", help="use the 3-second-window runs")
    parser.add_argument("--dir", type=Path, default=OUT, help=argparse.SUPPRESS)
    args = parser.parse_args()

    first = load(args.dir, args.first, not args.untrimmed)
    second = load(args.dir, args.second, not args.untrimmed)
    report(f"{args.first} alone", outcomes(first, None))
    report(f"{args.second} alone", outcomes(second, None))
    combined = outcomes(first, second)
    report(f"Two-stage: {args.first}, then {args.second} when unclear", combined)

    wrong = [o for o in combined if o.got != o.wanted]
    if wrong:
        print("\nTwo-stage mistakes (said → heard: got / wanted):")
        for o in wrong:
            print(f"  {o.condition:6} {o.said!r:32} → {o.heard}: {o.got} / {o.wanted}")


if __name__ == "__main__":
    main()
