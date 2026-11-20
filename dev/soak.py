"""The soak: watch Earwarden for hours while you work (Phase 4, milestone 7; the 8-hour test).

    uv run python dev/soak.py --hours 8 --home .tools/earwarden --log .tools/earwarden/soak.log

Run it beside `earwardend --voice --helper … 2>&1 | tee .tools/earwarden/soak.log`, with the AirPods
in and a few Claude Code sessions going in scratch projects. Every minute it samples the daemon's
and the helper's memory and CPU (`ps`), and reads the daemon's log for what the gate asks:

- memory growth: resident size at the start, the end and the peak (the target is 3 GB at most,
  and no steady climb)
- CPU when idle: the median of the minutes without a request (the target is under 2%)
- crashes: the helper disconnecting and reconnecting, and tracebacks in the log
- false nods: "nod seen" lines, one per answer window at most (the target is 1 an hour at most)
- every decision, by outcome, and every clip the daemon kept, so false approvals can be checked
  against the audio afterwards (P-20)

It writes one JSON line per sample to `<home>/soak.jsonl` and prints the summary at the end, or
when you stop it with Ctrl-C.
"""

from __future__ import annotations

import argparse
import itertools
import json
import re
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import ClassVar

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from earwarden import paths  # noqa: E402

SAMPLE_S = 60.0
MEMORY_TARGET_MB = 3 * 1024
IDLE_CPU_TARGET = 2.0
NODS_TARGET_PER_HOUR = 1.0


def pids(pattern: str) -> list[int]:
    out = subprocess.run(  # noqa: S603 - a fixed system tool and fixed arguments
        ["/usr/bin/pgrep", "-f", pattern], capture_output=True, text=True, check=False
    ).stdout
    return [int(p) for p in out.split()]


def usage(pid: int) -> tuple[float, float] | None:
    """Resident MB and %CPU for a process, or None if it's gone."""
    out = subprocess.run(  # noqa: S603 - a fixed system tool and fixed arguments
        ["/bin/ps", "-o", "rss=,%cpu=", "-p", str(pid)], capture_output=True, text=True, check=False
    ).stdout.split()
    if len(out) != 2:
        return None
    return int(out[0]) / 1024, float(out[1])


class LogCounts:
    """What the daemon's log says so far."""

    PATTERNS: ClassVar[dict[str, re.Pattern[str]]] = {
        "requests": re.compile(r"request req_\w+: \w+ in "),
        "allow": re.compile(r": allow \("),
        "deny": re.compile(r": deny \("),
        "handoff": re.compile(r": handoff \("),
        "nods_seen": re.compile(r"nod seen, ignored"),
        "nods_counted": re.compile(r"gesture: nod"),
        "shakes": re.compile(r"gesture: shake"),
        "helper_connected": re.compile(r"helper connected"),
        "helper_disconnected": re.compile(r"helper disconnected"),
        "tracebacks": re.compile(r"Traceback \(most recent call last\)"),
        "barge_ins": re.compile(r"barge-in: speech over Earwarden"),
        "false_approval_checks": re.compile(r"recognized: approve"),
    }

    def __init__(self, path: Path | None) -> None:
        self.path = path
        self.offset = 0
        self.counts = dict.fromkeys(self.PATTERNS, 0)

    def read(self) -> dict[str, int]:
        if self.path is None or not self.path.exists():
            return dict(self.counts)
        with self.path.open("r", encoding="utf-8", errors="replace") as file:
            file.seek(self.offset)
            for line in file:
                for key, pattern in self.PATTERNS.items():
                    if pattern.search(line):
                        self.counts[key] += 1
            self.offset = file.tell()
        return dict(self.counts)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hours", type=float, default=8.0)
    parser.add_argument("--home", help="Earwarden's home, as for earwardend")
    parser.add_argument("--log", help="the daemon's log file (tee earwardend's output to it)")
    args = parser.parse_args()
    where = paths.resolve(args.home)
    out = where.state_dir / "soak.jsonl"
    counts = LogCounts(Path(args.log) if args.log else None)
    samples: list[dict[str, float | int | None]] = []
    start = time.monotonic()
    end = start + args.hours * 3600
    print(f"Soaking for {args.hours:g} hours; samples go to {out}. Ctrl-C ends it early.")
    try:
        while time.monotonic() < end:
            daemon = pids("bin/earwardend")
            helper = pids("MacOS/earwarden-motion")
            d = usage(daemon[0]) if daemon else None
            h = usage(helper[0]) if helper else None
            seen = counts.read()
            sample: dict[str, float | int | None] = {
                "t": round(time.monotonic() - start),
                "daemon_mb": round(d[0]) if d else None,
                "daemon_cpu": d[1] if d else None,
                "helper_mb": round(h[0]) if h else None,
                "helper_cpu": h[1] if h else None,
                **seen,
            }
            samples.append(sample)
            with out.open("a", encoding="utf-8") as file:
                file.write(json.dumps(sample) + "\n")
            minutes = (time.monotonic() - start) / 60
            print(
                f"  {minutes:5.0f} min: daemon {sample['daemon_mb']} MB {sample['daemon_cpu']}% "
                f"cpu, helper {sample['helper_mb']} MB; {seen['requests']} requests, "
                f"{seen['nods_seen']} nods seen",
                end="\r",
            )
            time.sleep(SAMPLE_S)
    except KeyboardInterrupt:
        print("\nStopped early.")
    return report(samples, counts.read())


def report(samples: list[dict[str, float | int | None]], seen: dict[str, int]) -> int:
    if not samples:
        print("No samples.")
        return 1
    hours = max(float(samples[-1]["t"] or 0) / 3600, 1 / 60)
    memory = [float(s["daemon_mb"]) for s in samples if s["daemon_mb"] is not None]
    gone = sum(1 for s in samples if s["daemon_mb"] is None)
    idle_cpu = [
        float(s["daemon_cpu"])
        for prev, s in itertools.pairwise(samples)
        if s["daemon_cpu"] is not None and s["requests"] == prev["requests"]
    ]
    problems: list[str] = []
    print(f"\nSoak: {hours:.1f} hours, {len(samples)} samples")
    if memory:
        growth = memory[-1] - memory[0]
        print(
            f"memory: {memory[0]:.0f} MB at the start, {memory[-1]:.0f} MB at the end, "
            f"{max(memory):.0f} MB at the peak ({growth:+.0f} MB)"
        )
        if max(memory) > MEMORY_TARGET_MB:
            problems.append(f"memory over {MEMORY_TARGET_MB} MB")
        if hours >= 1 and growth > 0.25 * memory[0] and growth > 200:
            problems.append(f"memory grew by {growth:.0f} MB")
    if gone:
        problems.append(f"the daemon was missing in {gone} samples")
    if idle_cpu:
        median = statistics.median(idle_cpu)
        print(f"cpu when idle: median {median:.1f}% over {len(idle_cpu)} quiet minutes")
        if median > IDLE_CPU_TARGET:
            problems.append(f"idle cpu over {IDLE_CPU_TARGET}%")
    reconnects = max(seen["helper_connected"] - 1, 0)
    print(f"helper: {reconnects} reconnects, {seen['helper_disconnected']} disconnects")
    if seen["tracebacks"]:
        problems.append(f"{seen['tracebacks']} tracebacks in the log")
    nods = seen["nods_seen"] + seen["nods_counted"]
    print(
        f"nods inside answer windows: {nods} ({nods / hours:.1f} an hour; the target is at most "
        f"{NODS_TARGET_PER_HOUR:g}), shakes {seen['shakes']}"
    )
    if nods / hours > NODS_TARGET_PER_HOUR:
        problems.append("false nods over the target")
    print(
        f"decisions: {seen['requests']} requests; {seen['allow']} allowed, {seen['deny']} denied, "
        f"{seen['handoff']} to the screen; {seen['barge_ins']} barge-ins"
    )
    print(
        "false approvals: check every allowed request's clip in the home's audio folder "
        "(clips.jsonl) against what you said"
    )
    if problems:
        print("PROBLEMS: " + "; ".join(problems))
        return 1
    print("No problems found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
