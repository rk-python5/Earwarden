"""The Step 0 hook probe must behave like a safe hook: exit 0, print only on PermissionRequest."""

import json
import os
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
PROBE = ROOT / "spikes" / "hook_probe" / "probe_hook.py"
CLI = ROOT / "spikes" / "hook_probe" / "probe_cli.py"
OTHER_EVENTS = ["PreToolUse", "PostToolUse", "Notification", "Stop", "SessionStart", "SessionEnd"]


def request(event: str = "PermissionRequest") -> dict[str, Any]:
    return {
        "session_id": "s1",
        "cwd": "/Users/example/code/api",
        "permission_mode": "default",
        "hook_event_name": event,
        "tool_name": "Bash",
        "tool_input": {"command": "git push origin feature/login"},
    }


def run_hook(out: Path, stdin: str, mode: str | None = None) -> subprocess.CompletedProcess[str]:
    out.mkdir(parents=True, exist_ok=True)
    if mode is not None:
        (out / "mode").write_text(mode)
    env = {**os.environ, "EARSHOT_PROBE_DIR": str(out)}
    return subprocess.run(
        [sys.executable, str(PROBE), "hook"],
        input=stdin,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
        check=False,
    )


def run_cli(tmp: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "EARSHOT_PROBE_DIR": str(tmp / "out")}
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
        check=False,
    )


def events(out: Path) -> list[dict[str, Any]]:
    lines = (out / "events.jsonl").read_text().splitlines()
    return [json.loads(line) for line in lines]


def test_default_mode_prints_nothing_and_logs_the_payload(tmp_path: Path) -> None:
    result = run_hook(tmp_path, json.dumps(request()))
    assert (result.returncode, result.stdout) == (0, "")
    [record] = events(tmp_path)
    assert (record["event"], record["phase"], record["mode"]) == (
        "PermissionRequest",
        "end",
        "none",
    )
    assert record["payload"]["tool_input"] == {"command": "git push origin feature/login"}


@pytest.mark.parametrize("behavior", ["allow", "deny"])
def test_allow_and_deny_go_through_the_decision_object(tmp_path: Path, behavior: str) -> None:
    result = run_hook(tmp_path, json.dumps(request()), mode=behavior)
    assert result.returncode == 0
    output = json.loads(result.stdout)["hookSpecificOutput"]
    assert output["hookEventName"] == "PermissionRequest"
    assert output["decision"]["behavior"] == behavior
    assert ("message" in output["decision"]) == (behavior == "deny")


@pytest.mark.parametrize("event", OTHER_EVENTS)
def test_other_events_never_print(tmp_path: Path, event: str) -> None:
    result = run_hook(tmp_path, json.dumps(request(event)), mode="allow")
    assert (result.returncode, result.stdout) == (0, "")


@pytest.mark.parametrize("stdin", ["", "not json", "[1, 2]", '{"hook_event_name": 7}'])
def test_bad_input_exits_zero_and_prints_nothing(tmp_path: Path, stdin: str) -> None:
    result = run_hook(tmp_path, stdin, mode="allow")
    assert (result.returncode, result.stdout) == (0, "")


@pytest.mark.parametrize("mode", ["sure", "allow-everything", "hold soon", ""])
def test_unknown_mode_means_no_decision(tmp_path: Path, mode: str) -> None:
    result = run_hook(tmp_path, json.dumps(request()), mode=mode)
    assert (result.returncode, result.stdout) == (0, "")


def test_hold_then_allow(tmp_path: Path) -> None:
    start = time.monotonic()
    result = run_hook(tmp_path, json.dumps(request()), mode="hold-allow 0.3")
    assert time.monotonic() - start >= 0.3
    assert json.loads(result.stdout)["hookSpecificOutput"]["decision"]["behavior"] == "allow"
    assert [e["phase"] for e in events(tmp_path)] == ["hold-start", "end"]


def test_signal_during_hold_is_logged_and_exits_zero(tmp_path: Path) -> None:
    (tmp_path / "mode").write_text("hold-allow 30")
    env = {**os.environ, "EARSHOT_PROBE_DIR": str(tmp_path)}
    with subprocess.Popen(
        [sys.executable, str(PROBE), "hook"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        env=env,
    ) as proc:
        assert proc.stdin is not None
        assert proc.stdout is not None
        proc.stdin.write(json.dumps(request()))
        proc.stdin.close()
        log = tmp_path / "events.jsonl"
        deadline = time.monotonic() + 10
        while not (log.exists() and "hold-start" in log.read_text()):
            assert time.monotonic() < deadline, "the probe never started holding"
            time.sleep(0.02)
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=10)
        stdout = proc.stdout.read()
    assert (proc.returncode, stdout) == (0, "")
    assert [e["phase"] for e in events(tmp_path)] == ["hold-start", "signal"]
    assert events(tmp_path)[-1]["signal"] == "SIGTERM"


def test_install_writes_hooks_for_every_event(tmp_path: Path) -> None:
    project = tmp_path / "project"
    result = run_cli(tmp_path, "install", str(project))
    assert result.returncode == 0, result.stderr
    settings = json.loads((project / ".claude" / "settings.local.json").read_text())
    hooks = settings["hooks"]
    assert set(hooks) == {"PermissionRequest", *OTHER_EVENTS}
    handler = hooks["PermissionRequest"][0]["hooks"][0]
    assert handler["timeout"] == 300
    assert shlex.split(handler["command"]) == [sys.executable, str(PROBE), "hook"]
    assert run_cli(tmp_path, "install", str(project)).returncode == 1  # never overwrites


def test_hold_modes_need_seconds(tmp_path: Path) -> None:
    assert run_cli(tmp_path, "mode", "hold").returncode == 1
    assert run_cli(tmp_path, "mode", "hold", "2.5").returncode == 0
    assert (tmp_path / "out" / "mode").read_text().strip() == "hold 2.5"


def test_report_links_the_tool_events_and_writes_fixtures(tmp_path: Path) -> None:
    out = tmp_path / "out"
    assert run_cli(tmp_path, "mode", "deny").returncode == 0
    for event in ("PreToolUse", "PermissionRequest", "PostToolUse"):
        assert run_hook(out, json.dumps(request(event))).returncode == 0
    notification = {
        "hook_event_name": "Notification",
        "notification_type": "permission_prompt",
        "message": "Claude needs your permission to use Bash",
    }
    assert run_hook(out, json.dumps(notification)).returncode == 0
    report = run_cli(tmp_path, "report", "--fixtures", str(tmp_path / "fixtures"))
    assert report.returncode == 0, report.stderr
    row = next(line for line in report.stdout.splitlines() if line.strip().startswith("Bash"))
    assert "deny" in row
    assert "yes" in row  # the PostToolUse after the request was linked to it
    assert "permission_prompt: Claude needs your permission" in report.stdout
    assert "PermissionRequest: " in report.stdout
    assert json.loads((tmp_path / "fixtures" / "PermissionRequest.json").read_text())["tool_name"]


def test_bench_runs(tmp_path: Path) -> None:
    result = run_cli(tmp_path, "bench", "--runs", "2")
    assert result.returncode == 0, result.stderr
    assert result.stdout.count("median") == 2
