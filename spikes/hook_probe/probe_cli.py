#!/usr/bin/env python3
"""Tools around the hook probe: install it, switch modes, benchmark it, report what it saw.

    python probe_cli.py install ~/earshot-probe     # write .claude/settings.local.json there
    python probe_cli.py mode hold 30                # set the PermissionRequest behaviour
    python probe_cli.py bench                       # cost of starting the hook process
    python probe_cli.py report [--fixtures DIR]     # timings, field inventory, sample payloads

Run it with the interpreter that should run the hook (`uv run python …` from the repo root uses
the project's .venv, a stable path). Standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import statistics
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
PROBE = HERE / "probe_hook.py"
MODES = ("none", "allow", "deny", "hold", "hold-allow", "hold-deny")
# Events with matchers take "*"; the rest take no matcher. PermissionRequest gets a long timeout
# so Claude Code never cuts a held hook short during the spike.
TOOL_EVENTS = ("PreToolUse", "PermissionRequest", "PostToolUse")
OTHER_EVENTS = ("Notification", "Stop", "SessionStart", "SessionEnd")
SAMPLE_REQUEST = {
    "session_id": "bench",
    "transcript_path": "/Users/example/.claude/projects/api/session.jsonl",
    "cwd": "/Users/example/code/api",
    "permission_mode": "default",
    "hook_event_name": "PermissionRequest",
    "tool_name": "Bash",
    "tool_input": {"command": "git push origin feature/login"},
}


def out_dir() -> Path:
    override = os.environ.get("EARSHOT_PROBE_DIR")
    return Path(override) if override else HERE / "out"


def hook_command() -> str:
    return f"{shlex.quote(sys.executable)} {shlex.quote(str(PROBE))} hook"


def settings() -> dict[str, Any]:
    command = hook_command()
    hooks: dict[str, Any] = {}
    for event in TOOL_EVENTS:
        handler: dict[str, Any] = {"type": "command", "command": command}
        if event == "PermissionRequest":
            handler["timeout"] = 300
        hooks[event] = [{"matcher": "*", "hooks": [handler]}]
    for event in OTHER_EVENTS:
        hooks[event] = [{"hooks": [{"type": "command", "command": command}]}]
    return {"hooks": hooks}


def cmd_install(args: argparse.Namespace) -> int:
    project = Path(args.project).expanduser().resolve()
    target = project / ".claude" / "settings.local.json"
    if target.exists() and not args.force:
        print(f"{target} exists; pass --force to replace it", file=sys.stderr)
        return 1
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(settings(), indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {target}")
    print(f"Hook command: {hook_command()}")
    print(f"Log: {out_dir() / 'events.jsonl'}")
    return 0


def cmd_mode(args: argparse.Namespace) -> int:
    if args.name.startswith("hold") and args.seconds is None:
        print("hold modes need a number of seconds", file=sys.stderr)
        return 1
    text = args.name if args.seconds is None else f"{args.name} {args.seconds:g}"
    out_dir().mkdir(parents=True, exist_ok=True)
    (out_dir() / "mode").write_text(text + "\n", encoding="utf-8")
    print(f"PermissionRequest mode: {text}")
    return 0


def _time_runs(argv: list[str], runs: int, env: dict[str, str]) -> list[float]:
    payload = json.dumps(SAMPLE_REQUEST)
    times = []
    for _ in range(runs):
        start = time.perf_counter()
        subprocess.run(argv, input=payload, text=True, capture_output=True, env=env, check=True)
        times.append((time.perf_counter() - start) * 1000)
    return times


def cmd_bench(args: argparse.Namespace) -> int:
    with tempfile.TemporaryDirectory() as scratch:
        env = {**os.environ, "EARSHOT_PROBE_DIR": scratch}
        variants = {
            "python probe_hook.py hook": [sys.executable, str(PROBE), "hook"],
            "python -I -S probe_hook.py hook": [sys.executable, "-I", "-S", str(PROBE), "hook"],
        }
        print(f"Interpreter: {sys.executable} ({sys.version.split()[0]}), {args.runs} runs each")
        for label, argv in variants.items():
            _time_runs(argv, 3, env)  # warm the file cache
            times = sorted(_time_runs(argv, args.runs, env))
            p95 = times[min(len(times) - 1, round(0.95 * (len(times) - 1)))]
            print(
                f"  {label:34} median {statistics.median(times):6.1f} ms   "
                f"p95 {p95:6.1f} ms   min {times[0]:6.1f} ms"
            )
    return 0


def load_events(path: Path) -> list[dict[str, Any]]:
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict):
            events.append(record)
    return events


def _ms(later_ns: int, earlier_ns: int) -> float:
    return (later_ns - earlier_ns) / 1e6


def _key(record: dict[str, Any]) -> tuple[Any, ...]:
    payload = record.get("payload", {})
    return (
        payload.get("session_id"),
        payload.get("tool_name"),
        json.dumps(payload.get("tool_input"), sort_keys=True),
    )


def permission_rows(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per PermissionRequest, linked to the PreToolUse before it and PostToolUse after."""
    finished = [e for e in events if e.get("phase") == "end"]
    rows = []
    by_start: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for record in events:
        if record.get("event") == "PermissionRequest":
            by_start[(record.get("pid"), record.get("t_start_ns"))].append(record)
    for (_, t_start), records in sorted(by_start.items(), key=lambda item: item[0][1] or 0):
        phases = {r.get("phase"): r for r in records}
        base = records[0]
        payload = base.get("payload", {})
        key = _key(base)
        pre = [
            e
            for e in finished
            if e.get("event") == "PreToolUse" and _key(e) == key and e["t_end_ns"] <= t_start
        ]
        post = [
            e
            for e in finished
            if e.get("event") == "PostToolUse" and _key(e) == key and e["t_start_ns"] >= t_start
        ]
        end = phases.get("end")
        if end:
            ended = "end"
        elif "signal" in phases:
            ended = "signal " + str(phases["signal"].get("signal"))
        else:
            ended = "vanished: no end record, so probably killed with SIGKILL"
        rows.append(
            {
                "tool": payload.get("tool_name"),
                "input": json.dumps(payload.get("tool_input"))[:60],
                "mode": f"{base.get('mode')} {base.get('hold_s') or ''}".strip(),
                "ended": ended,
                "hook_ms": _ms(end["t_end_ns"], t_start) if end else None,
                "pre_to_request_ms": _ms(t_start, pre[-1]["t_end_ns"]) if pre else None,
                "request_to_post_ms": (
                    _ms(post[0]["t_start_ns"], end["t_end_ns"]) if post and end else None
                ),
                "tool_ran": bool(post),
            }
        )
    return rows


def _fmt(value: float | None) -> str:
    return "—" if value is None else f"{value:.0f}"


def _sanitize(value: Any, home: str) -> Any:
    if isinstance(value, str):
        return value.replace(home, "~") if home else value
    if isinstance(value, dict):
        return {k: _sanitize(v, home) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize(v, home) for v in value]
    return value


def cmd_report(args: argparse.Namespace) -> int:
    path = out_dir() / "events.jsonl"
    if not path.exists():
        print(f"No log at {path}", file=sys.stderr)
        return 1
    events = load_events(path)
    print(f"{len(events)} records in {path}\n")

    print("PermissionRequest hooks (times in ms):")
    print(f"  {'tool':8} {'mode':14} {'hook':>6} {'pre→req':>8} {'req→post':>9} ran  ended / input")
    for row in permission_rows(events):
        print(
            f"  {row['tool'] or '?':8} {row['mode']:14} {_fmt(row['hook_ms']):>6} "
            f"{_fmt(row['pre_to_request_ms']):>8} {_fmt(row['request_to_post_ms']):>9} "
            f"{'yes' if row['tool_ran'] else 'no ':4} {row['ended']} / {row['input']}"
        )

    print("\nNotifications (seconds after the latest PermissionRequest hook started):")
    last_request_ns: int | None = None
    for record in sorted(events, key=lambda e: e.get("t_start_ns") or 0):
        payload = record.get("payload") or {}
        if record.get("event") == "PermissionRequest":
            last_request_ns = record.get("t_start_ns")
        elif record.get("event") == "Notification" and record.get("phase") == "end":
            offset = (
                "—"
                if last_request_ns is None
                else f"{(record['t_start_ns'] - last_request_ns) / 1e9:.1f}"
            )
            kind = payload.get("notification_type", "?")
            print(f"  +{offset:>6} s  {kind}: {str(payload.get('message', ''))[:70]}")

    print("\nFields seen per event:")
    fields: dict[str, set[str]] = defaultdict(set)
    samples: dict[str, dict[str, Any]] = {}
    for record in events:
        payload = record.get("payload")
        if record.get("phase") == "end" and isinstance(payload, dict):
            event = str(record.get("event"))
            fields[event].update(payload)
            samples.setdefault(event, payload)
    for event in sorted(fields):
        print(f"  {event}: {', '.join(sorted(fields[event]))}")

    if args.fixtures:
        target = Path(args.fixtures).expanduser()
        target.mkdir(parents=True, exist_ok=True)
        home = str(Path.home())
        for event, payload in samples.items():
            file = target / f"{event}.json"
            file.write_text(json.dumps(_sanitize(payload, home), indent=2) + "\n", encoding="utf-8")
        print(f"\nWrote {len(samples)} sample payloads to {target} (home directory shown as ~)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    commands = parser.add_subparsers(dest="command", required=True)

    install = commands.add_parser("install", help="write the probe hooks into a scratch project")
    install.add_argument("project")
    install.add_argument("--force", action="store_true")
    install.set_defaults(func=cmd_install)

    mode = commands.add_parser("mode", help="set what the probe answers to PermissionRequest")
    mode.add_argument("name", choices=MODES)
    mode.add_argument("seconds", nargs="?", type=float)
    mode.set_defaults(func=cmd_mode)

    bench = commands.add_parser("bench", help="time the hook process with a canned request")
    bench.add_argument("--runs", type=int, default=30)
    bench.set_defaults(func=cmd_bench)

    report = commands.add_parser("report", help="summarise out/events.jsonl")
    report.add_argument("--fixtures", help="also write one sanitized sample payload per event here")
    report.set_defaults(func=cmd_report)

    args = parser.parse_args()
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    sys.exit(main())
