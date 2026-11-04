"""A fake Claude Code: rehaan's captured Step 0 session, replayed through hook and daemon."""

from __future__ import annotations

import asyncio
import json
import plistlib
from pathlib import Path

import pytest
from conftest import StartDaemon
from harness import FIXTURES, run_hook

from earshot import audit, paths, service
from earshot.cli import main
from earshot.daemon.state import Pending
from earshot.voice.decider import Heard, VoiceDecider


class SaysYes:
    def __init__(self) -> None:
        self.said: list[str] = []

    def headset_ready(self) -> bool:
        return True

    def can_say(self, word: str) -> bool:
        return True

    async def say(self, text: str, chime: int | None = None) -> None:
        self.said.append(text)

    async def listen(self, seconds: float) -> Heard | None:
        return Heard("yes", "parakeet", 60)

    async def open_mic(self) -> None:
        pass

    async def close_mic(self) -> None:
        pass


class Away:
    def away(self) -> bool:
        return True


def replay() -> list[dict[str, object]]:
    lines = (FIXTURES / "probe_session.jsonl").read_text(encoding="utf-8").splitlines()
    return [r for r in map(json.loads, lines) if r["phase"] == "end"]


def test_the_captured_session_replays_cleanly(home: Path, start_daemon: StartDaemon) -> None:
    """Every hook call of a real session, in order: Bash `touch` commands aren't voice-approvable
    under the safety stub, so each is announced and handed to the screen, and nothing is printed
    but what Claude Code expects: nothing at all."""
    where = paths.resolve(str(home))
    voice = SaysYes()
    running = start_daemon(
        VoiceDecider(voice, Away(), reannounce_s=0),
        audit_log=audit.AuditLog(where.audit_dir, audit.load_key(where)),
    )
    requests = 0
    for record in replay():
        payload = record["payload"]
        assert isinstance(payload, dict)
        if record["event"] == "PermissionRequest":
            requests += 1
            assert run_hook(home, payload) == b""
        else:
            assert run_hook(home, payload, "--event") == b""
    running.wait_for(lambda d: len(d.resolved) == requests)
    running.wait_for(lambda d: len(d.sessions) == 0)  # the session ended
    assert all(r.outcome == "handoff" for r in running.daemon.resolved)
    assert voice.said
    assert all(s.endswith("It's on your screen.") for s in voice.said)
    running.stop()
    assert audit.verify(where.audit_dir, audit.load_key(where)) == []
    assert len(list(audit.AuditLog(where.audit_dir, audit.load_key(where)).records())) == requests


def test_an_edit_is_approved_by_voice_end_to_end(home: Path, start_daemon: StartDaemon) -> None:
    start_daemon(VoiceDecider(SaysYes(), Away(), reannounce_s=0))
    [request] = [r["payload"] for r in replay() if r["event"] == "PermissionRequest"][:1]
    assert isinstance(request, dict)
    request = request | {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": "/Users/rehaan/earshot-probe/notes.md",
            "old_string": "a",
            "new_string": "b",
        },
    }
    printed = json.loads(run_hook(home, request))
    assert printed["hookSpecificOutput"]["decision"] == {"behavior": "allow"}


def test_earshot_test_goes_through_the_running_daemon(
    home: Path, start_daemon: StartDaemon, capsys: pytest.CaptureFixture[str]
) -> None:
    running = start_daemon(VoiceDecider(SaysYes(), Away(), reannounce_s=0))
    assert main(["test", "--home", str(home)]) == 0
    assert "Result: allow" in capsys.readouterr().out
    assert running.daemon.resolved[-1].outcome == "allow"


def test_doctor_reports_what_is_missing(
    home: Path, start_daemon: StartDaemon, capsys: pytest.CaptureFixture[str]
) -> None:
    start_daemon()
    settings_file = home / "settings.json"
    assert main(["init", "--settings", str(settings_file), "--home", str(home)]) == 0
    code = main(["doctor", "--home", str(home), "--settings", str(settings_file)])
    out = capsys.readouterr().out
    assert "ok  hooks are in" in out
    assert "ok  the token is private" in out
    assert "ok  earshotd is running" in out
    assert code in (0, 1)  # the voice libraries only exist on the Mac


def test_the_launch_agent(tmp_path: Path) -> None:
    agent = plistlib.loads(
        service.agent(["--home", "/repo/.tools/earshot", "--voice"], tmp_path / "earshotd.log")
    )
    assert agent["Label"] == service.LABEL
    assert agent["ProgramArguments"][0].endswith("/earshotd")
    assert agent["ProgramArguments"][1:] == ["--home", "/repo/.tools/earshot", "--voice"]
    assert agent["KeepAlive"] is True
    assert agent["RunAtLoad"] is True


def test_pending_requests_carry_their_notes() -> None:
    """The decider's notes default to empty, so the audit log never sees stale ones."""
    assert asyncio.iscoroutinefunction(VoiceDecider.__call__)
    assert Pending.__dataclass_fields__["notes"].default_factory is not None
