"""Observe mode (D-021): one line per prompt, no command text, and a summary of the week."""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest
from conftest import StartDaemon
from harness import fixture, run_hook

from earwarden.cli import main, summarise


def test_observe_mode_logs_each_prompt_without_its_contents(
    home: Path, start_daemon: StartDaemon
) -> None:
    start_daemon(observe=True)
    assert run_hook(home, fixture("permission_request")) == b""
    edit = fixture("permission_request")
    edit["tool_name"] = "Edit"
    edit["tool_input"] = {"file_path": "src/app.py", "old_string": "secret=1", "new_string": "x"}
    assert run_hook(home, edit) == b""
    log = home / "observe.jsonl"
    assert stat.S_IMODE(log.stat().st_mode) == 0o600
    first, second = (json.loads(line) for line in log.read_text().splitlines())
    assert (first["tool"], first["voice_ok"], first["permission_mode"]) == (
        "Bash",
        False,
        "default",
    )
    assert first["session"] == "earwarden-probe"
    assert (second["tool"], second["voice_ok"]) == ("Edit", True)
    assert "touch" not in log.read_text()
    assert "secret" not in log.read_text()


def test_without_observe_mode_nothing_is_logged(home: Path, start_daemon: StartDaemon) -> None:
    start_daemon()
    run_hook(home, fixture("permission_request"))
    assert not (home / "observe.jsonl").exists()


def test_the_summary() -> None:
    records = [
        {
            "ts": "2026-11-05T09:00:00.000Z",
            "permission_mode": "auto",
            "tool": "Bash",
            "voice_ok": False,
            "reason": "command not on the test list",
        },
        {
            "ts": "2026-11-05T11:00:00.000Z",
            "permission_mode": "auto",
            "tool": "Edit",
            "voice_ok": True,
            "reason": "edit inside the project",
        },
        {
            "ts": "2026-11-06T09:00:00.000Z",
            "permission_mode": "default",
            "tool": "Bash",
            "voice_ok": False,
            "reason": "command not on the test list",
        },
    ]
    lines = summarise(records)
    assert lines[0].startswith("3 prompts from 05 Nov 09:00 to 06 Nov 09:00 UTC, on 2 day(s)")
    assert "1.5 a day" in lines[0]
    assert "Voice could approve 1 of them" in lines[1]
    assert "Permission mode: auto 2, default 1" in lines
    assert summarise([]) == ["No prompts recorded yet."]


def test_the_observe_command(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["observe", "--home", str(tmp_path)]) == 1
    (tmp_path / "observe.jsonl").write_text(
        '{"ts": "2026-11-05T09:00:00.000Z", "permission_mode": "auto", "tool": "Bash",'
        ' "voice_ok": false, "reason": "x"}\nnot json\n'
    )
    assert main(["observe", "--home", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "1 prompt from" in out
    assert "too little for a rate" in out
