#!/usr/bin/env python3
"""Claude Code hook probe for Earwarden's Step 0 hook spike.

Claude Code runs this as a command hook (`probe_hook.py hook`) for every event the probe is
installed on. It appends one JSON line per invocation to `out/events.jsonl` and, for
`PermissionRequest` only, answers according to the mode file `out/mode`:

    none            print nothing; Claude Code shows its normal dialog
    allow / deny    print an allow or deny decision at once
    hold N          wait N seconds, then print nothing
    hold-allow N    wait N seconds, then allow
    hold-deny N     wait N seconds, then deny

Like the real `earwarden-hook`, it uses only the standard library, always exits 0, and never prints
anything except one decision object on `PermissionRequest`.
"""

from __future__ import annotations

import contextlib
import json
import os
import signal
import sys
import time
from pathlib import Path
from types import FrameType
from typing import Any

T0_NS = time.time_ns()

MODES = {"none", "allow", "deny", "hold", "hold-allow", "hold-deny"}
BEHAVIOR = {"allow": "allow", "deny": "deny", "hold-allow": "allow", "hold-deny": "deny"}
DENY_MESSAGE = "Denied by the Earwarden hook probe (Step 0 spike)."


def out_dir() -> Path:
    override = os.environ.get("EARWARDEN_PROBE_DIR")
    return Path(override) if override else Path(__file__).resolve().parent / "out"


def log(record: dict[str, Any]) -> None:
    """Append one line with a single write, so parallel hooks don't interleave."""
    directory = out_dir()
    directory.mkdir(parents=True, exist_ok=True)
    line = (json.dumps(record, sort_keys=True, default=repr) + "\n").encode()
    fd = os.open(directory / "events.jsonl", os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(fd, line)
    finally:
        os.close(fd)


def read_mode() -> tuple[str, float]:
    try:
        words = (out_dir() / "mode").read_text(encoding="utf-8").split()
    except OSError:
        return "none", 0.0
    if not words or words[0] not in MODES:
        return "none", 0.0
    try:
        seconds = float(words[1]) if len(words) > 1 else 0.0
    except ValueError:
        return "none", 0.0
    return words[0], max(seconds, 0.0)


def decision(behavior: str) -> str:
    body: dict[str, Any] = {"behavior": behavior}
    if behavior == "deny":
        body["message"] = DENY_MESSAGE
    return json.dumps(
        {"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": body}}
    )


def log_signals(base: dict[str, Any]) -> None:
    """Record how Claude Code ends a hook that is still waiting, then exit 0 quietly."""

    def handler(signum: int, frame: FrameType | None) -> None:
        log(
            {
                **base,
                "phase": "signal",
                "signal": signal.Signals(signum).name,
                "t_ns": time.time_ns(),
            }
        )
        os._exit(0)

    for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(signum, handler)


def run_hook() -> None:
    record: dict[str, Any] = {
        "t_start_ns": T0_NS,
        "pid": os.getpid(),
        "ppid": os.getppid(),
        "argv": sys.argv[1:],
    }
    try:
        raw = sys.stdin.read()
        payload: Any = json.loads(raw) if raw.strip() else {}
    except (OSError, ValueError) as exc:
        payload = {"_error": repr(exc)}
    if not isinstance(payload, dict):
        payload = {"_not_an_object": payload}
    event = payload.get("hook_event_name", "?")
    record.update(event=event, t_read_ns=time.time_ns(), payload=payload)

    output = ""
    if event == "PermissionRequest":
        mode, seconds = read_mode()
        record.update(mode=mode, hold_s=seconds)
        if mode.startswith("hold"):
            log({**record, "phase": "hold-start", "t_ns": time.time_ns()})
            log_signals(record)
            time.sleep(seconds)
        if mode in BEHAVIOR:
            output = decision(BEHAVIOR[mode])

    log({**record, "phase": "end", "output": output, "t_end_ns": time.time_ns()})
    if output:
        sys.stdout.write(output)
        sys.stdout.flush()


def main() -> None:
    if sys.argv[1:2] != ["hook"]:
        sys.stderr.write("usage: probe_hook.py hook   (run by Claude Code; see README.md)\n")
        return
    try:
        run_hook()
    except BaseException as exc:  # nothing may escape a hook
        with contextlib.suppress(BaseException):
            log({"phase": "error", "error": repr(exc), "t_ns": time.time_ns()})


if __name__ == "__main__":
    main()
    os._exit(0)
