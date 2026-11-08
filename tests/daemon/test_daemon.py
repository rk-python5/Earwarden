"""earshotd with the real hook: decisions, refusals, sessions, and every way a wait ends (D-020)."""

from __future__ import annotations

import asyncio
import gc
import json
import os
import signal
import socket
import stat
import subprocess
import sys
import time
import warnings
from pathlib import Path
from typing import Any

import pytest
from conftest import StartDaemon
from harness import RunningDaemon, finish, fixture, never, run_hook, start_hook

from earshot import auth, contracts, paths, wire
from earshot.daemon import server
from earshot.daemon.server import AlreadyRunningError, decision, open_socket
from earshot.daemon.state import Pending

ALLOW = {
    "hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": {"behavior": "allow"}}
}


def answering(outcome: contracts.Outcome, message: str | None = None) -> server.Decider:
    async def decide(pending: Pending) -> contracts.Decision:
        return contracts.Decision(v=1, id=pending.request.id, outcome=outcome, message=message)

    return decide


def raw_exchange(home: Path, line: bytes, timeout: float = 5) -> bytes:
    """Send one raw line and return whatever comes back before the daemon closes."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.settimeout(timeout)
        conn.connect(str(home / "earshotd.sock"))
        conn.sendall(line)
        data = b""
        while chunk := conn.recv(4096):
            data += chunk
        return data


def token(home: Path) -> str:
    return (home / "token").read_text(encoding="ascii").strip()


# Setup and privacy


def test_the_socket_token_and_folder_are_private(home: Path, start_daemon: StartDaemon) -> None:
    start_daemon()
    assert stat.S_IMODE(home.stat().st_mode) == 0o700
    assert stat.S_IMODE((home / "earshotd.sock").stat().st_mode) == 0o600
    assert stat.S_IMODE((home / "token").stat().st_mode) == 0o600
    assert len(token(home)) == 64


def test_stopping_removes_the_socket(home: Path, start_daemon: StartDaemon) -> None:
    running = start_daemon()
    running.stop()
    assert not (home / "earshotd.sock").exists()
    assert running.error is None


def test_stopping_just_after_a_connection_leaks_nothing(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """In Python 3.11, closing the server mid-accept drops the connection without closing it."""
    leaks: list[str] = []
    monkeypatch.setattr(sys, "unraisablehook", lambda u: leaks.append(repr(u.exc_value)))
    with warnings.catch_warnings():
        warnings.simplefilter("error", ResourceWarning)
        for _ in range(50):
            running = RunningDaemon(home, server.hand_off, server.MAX_WAIT_S)
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
                conn.connect(str(home / "earshotd.sock"))
            running.stop()
            del running
            gc.collect()
    assert leaks == []


def test_a_second_daemon_refuses_to_start(home: Path, start_daemon: StartDaemon) -> None:
    start_daemon()
    with pytest.raises(AlreadyRunningError):
        open_socket(home / "earshotd.sock")


def test_a_file_in_the_sockets_place_is_left_alone(home: Path) -> None:
    (home / "earshotd.sock").write_text("not a socket", encoding="utf-8")
    with pytest.raises(AlreadyRunningError):
        open_socket(home / "earshotd.sock")
    assert (home / "earshotd.sock").read_text(encoding="utf-8") == "not a socket"


# Decisions


def test_for_now_every_request_goes_to_the_screen(home: Path, start_daemon: StartDaemon) -> None:
    running = start_daemon()
    assert run_hook(home, fixture("permission_request")) == b""
    [resolved] = running.daemon.resolved
    assert (resolved.outcome, resolved.reason, resolved.tool_name) == ("handoff", "decided", "Bash")


def test_an_allow_reaches_the_hook(home: Path, start_daemon: StartDaemon) -> None:
    start_daemon(answering("allow"))
    assert json.loads(run_hook(home, fixture("permission_request"))) == ALLOW


def test_a_deny_carries_its_message(home: Path, start_daemon: StartDaemon) -> None:
    start_daemon(answering("deny", "use poetry instead"))
    printed = json.loads(run_hook(home, fixture("permission_request")))
    assert printed["hookSpecificOutput"]["decision"] == {
        "behavior": "deny",
        "message": "use poetry instead",
    }


def test_three_sessions_wait_at_once_and_each_gets_its_own_answer(
    home: Path, start_daemon: StartDaemon
) -> None:
    arrived: set[str] = set()

    async def allow_once_all_three_wait(pending: Pending) -> contracts.Decision:
        arrived.add(pending.request.id)
        while len(arrived) < 3:  # all three are waiting at the same time
            await asyncio.sleep(0.01)
        return decision(pending, "allow")

    running = start_daemon(allow_once_all_three_wait)
    hooks = []
    for name in ("api", "docs", "deploy"):
        payload = fixture("permission_request")
        payload["session_id"] = f"session-{name}"
        payload["cwd"] = f"/Users/rehaan/code/{name}"
        hooks.append(start_hook(home, payload))
    assert [json.loads(finish(proc)) for proc in hooks] == [ALLOW] * 3
    sessions = running.daemon.sessions.all()
    assert sorted(s.name for s in sessions) == ["api", "deploy", "docs"]
    assert len({s.chime for s in sessions}) == 3


def test_a_failing_decider_hands_off(home: Path, start_daemon: StartDaemon) -> None:
    async def broken(pending: Pending) -> contracts.Decision:
        raise RuntimeError("the speech stack fell over")

    running = start_daemon(broken)
    assert run_hook(home, fixture("permission_request")) == b""
    assert running.daemon.resolved[-1].outcome == "handoff"


def test_an_answer_for_another_request_hands_off(home: Path, start_daemon: StartDaemon) -> None:
    async def confused(pending: Pending) -> contracts.Decision:
        return contracts.Decision(v=1, id="req_00000000000000000000", outcome="allow")

    start_daemon(confused)
    assert run_hook(home, fixture("permission_request")) == b""


# Refusals: no reply, so the hook prints nothing


def request_line(home: Path, **changes: Any) -> bytes:
    message = {
        "v": 1,
        "id": wire.new_request_id(),
        "token": token(home),
        "source": "claude_code",
        "session_id": "s1",
        "cwd": "/Users/rehaan/code/api",
        "permission_mode": "default",
        "tool_name": "Bash",
        "tool_input": {"command": "pytest"},
        "received_at": wire.utc_timestamp(),
    }
    message.update(changes)
    return wire.encode(message)


def test_a_wrong_token_gets_no_reply(home: Path, start_daemon: StartDaemon) -> None:
    running = start_daemon(answering("allow"))
    assert raw_exchange(home, request_line(home, token="ab" * 32)) == b""
    assert len(running.daemon.resolved) == 0
    assert len(running.daemon.sessions) == 0


@pytest.mark.parametrize(
    "line",
    [
        b"allow everything\n",
        b"[1, 2, 3]\n",
        b'{"v": 1}\n',
        b"\n",
    ],
    ids=["not json", "a list", "missing fields", "empty line"],
)
def test_garbage_gets_no_reply(home: Path, start_daemon: StartDaemon, line: bytes) -> None:
    running = start_daemon(answering("allow"))
    assert raw_exchange(home, line) == b""
    assert len(running.daemon.resolved) == 0


@pytest.mark.parametrize(
    "changes",
    [{"v": 2}, {"v": True}, {"approve": True}, {"cwd": "relative/path"}],
    ids=["version 2", "version true", "unknown field", "relative cwd"],
)
def test_a_request_that_breaks_the_contract_gets_no_reply(
    home: Path, start_daemon: StartDaemon, changes: dict[str, Any]
) -> None:
    running = start_daemon(answering("allow"))
    assert raw_exchange(home, request_line(home, **changes)) == b""
    assert len(running.daemon.resolved) == 0


def test_a_slow_client_is_dropped(
    home: Path, start_daemon: StartDaemon, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(server, "READ_TIMEOUT_S", 0.2)
    start_daemon(answering("allow"))
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.settimeout(5)
        conn.connect(str(home / "earshotd.sock"))
        start = time.monotonic()
        assert conn.recv(10) == b""  # closed without a word
        assert time.monotonic() - start < 3


def test_an_oversized_line_gets_no_reply(home: Path, start_daemon: StartDaemon) -> None:
    start_daemon(answering("allow"))
    huge = request_line(home, tool_input={"content": "x" * (wire.MAX_REQUEST_BYTES + 10_000)})
    try:
        reply = raw_exchange(home, huge)
    except (BrokenPipeError, ConnectionResetError):
        reply = b""  # the daemon hung up while we were still sending
    assert reply == b""


# Sessions


def test_session_events_keep_the_registry(home: Path, start_daemon: StartDaemon) -> None:
    running = start_daemon()
    sessions = running.daemon.sessions
    run_hook(home, fixture("session_start"), "--event")
    running.wait_for(lambda d: len(d.sessions) == 1)
    [session] = sessions.all()
    assert (session.name, session.model, session.chime) == ("earshot-probe", "claude-sonnet-5-5", 0)
    run_hook(home, fixture("stop"), "--event")
    running.wait_for(lambda d: session.last_message is not None)
    assert session.last_message is not None
    assert session.last_message.startswith("I ran `touch probe-1.txt`")
    run_hook(home, fixture("session_end"), "--event")
    running.wait_for(lambda d: len(d.sessions) == 0)


def test_a_request_from_an_unknown_session_registers_it(
    home: Path, start_daemon: StartDaemon
) -> None:
    running = start_daemon()
    run_hook(home, fixture("permission_request"))
    [session] = running.daemon.sessions.all()
    assert session.session_id == fixture("permission_request")["session_id"]


# How a wait ends (D-020)


def test_approving_on_screen_silences_the_waiting_prompt(
    home: Path, start_daemon: StartDaemon
) -> None:
    """You approve in Claude Code's dialog, the tool runs, and its PostToolUse ends the wait."""
    running = start_daemon(never)
    waiting = start_hook(home, fixture("permission_request"))
    running.wait_for(lambda d: len(d.pending) == 1)
    run_hook(home, fixture("post_tool_use"), "--event")
    assert finish(waiting) == b""
    [resolved] = running.daemon.resolved
    assert (resolved.outcome, resolved.reason) == ("handoff", "tool_ran")


def test_an_edit_to_build_config_marks_the_session(home: Path, start_daemon: StartDaemon) -> None:
    """P-01: after conftest.py changes, `pytest` runs new code, so it's no longer tier 1."""
    running = start_daemon(never)
    edited = fixture("post_tool_use")
    edited["tool_name"] = "Write"
    edited["tool_input"] = {"file_path": f"{edited['cwd']}/tests/conftest.py", "content": "x"}
    run_hook(home, edited, "--event")
    running.wait_for(lambda d: any(s.config_edited for s in d.sessions.all()))


def test_another_tool_run_leaves_the_prompt_waiting(home: Path, start_daemon: StartDaemon) -> None:
    running = start_daemon(never)
    waiting = start_hook(home, fixture("permission_request"))
    running.wait_for(lambda d: len(d.pending) == 1)
    other = fixture("post_tool_use")
    other["tool_input"] = {"command": "touch something-else.txt"}
    run_hook(home, other, "--event")
    time.sleep(0.3)
    assert len(running.daemon.pending) == 1
    waiting.terminate()
    finish(waiting)


def test_no_or_esc_in_the_dialog_cancels_the_prompt(home: Path, start_daemon: StartDaemon) -> None:
    """No or Esc makes Claude Code send the hook SIGTERM; its socket closes."""
    running = start_daemon(never)
    waiting = start_hook(home, fixture("permission_request"))
    running.wait_for(lambda d: len(d.pending) == 1)
    waiting.send_signal(signal.SIGTERM)
    assert finish(waiting) == b""
    running.wait_for(lambda d: len(d.resolved) == 1)
    [resolved] = running.daemon.resolved
    assert (resolved.outcome, resolved.reason) == ("cancelled", "hook_closed")
    assert len(running.daemon.pending) == 0


def test_the_session_ending_cancels_its_prompts(home: Path, start_daemon: StartDaemon) -> None:
    running = start_daemon(never)
    waiting = start_hook(home, fixture("permission_request"))
    running.wait_for(lambda d: len(d.pending) == 1)
    run_hook(home, fixture("session_end"), "--event")
    assert finish(waiting) == b""
    assert running.daemon.resolved[-1].reason == "session_ended"


def test_the_wait_limit_hands_off(home: Path, start_daemon: StartDaemon) -> None:
    running = start_daemon(never, max_wait_s=0.3)
    assert run_hook(home, fixture("permission_request")) == b""
    assert running.daemon.resolved[-1].reason == "timeout"


def test_stopping_hands_waiting_prompts_to_the_screen(
    home: Path, start_daemon: StartDaemon
) -> None:
    running = start_daemon(never)
    waiting = start_hook(home, fixture("permission_request"))
    running.wait_for(lambda d: len(d.pending) == 1)
    running.stop()
    assert finish(waiting) == b""
    assert running.daemon.resolved[-1].reason == "shutdown"


# The earshotd command


def start_earshotd(home: Path) -> subprocess.Popen[bytes]:
    proc = subprocess.Popen(
        [sys.executable, "-m", "earshot.daemon.cli", "--home", str(home)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    deadline = time.monotonic() + 15
    while True:  # listening, not just a socket file: a crashed daemon leaves one behind
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
                probe.connect(str(home / "earshotd.sock"))
            return proc
        except OSError:
            assert proc.poll() is None, proc.stderr.read() if proc.stderr else b""
            assert time.monotonic() < deadline
            time.sleep(0.05)


def stop_earshotd(proc: subprocess.Popen[bytes]) -> int:
    proc.send_signal(signal.SIGTERM)
    returncode = proc.wait(timeout=10)
    if proc.stderr:
        proc.stderr.close()
    return returncode


def test_earshotd_runs_and_stops_cleanly(home: Path) -> None:
    proc = start_earshotd(home)
    try:
        assert run_hook(home, fixture("permission_request")) == b""
    finally:
        assert stop_earshotd(proc) == 0
    assert not (home / "earshotd.sock").exists()


def test_a_second_earshotd_says_so(home: Path) -> None:
    first = start_earshotd(home)
    try:
        second = subprocess.run(
            [sys.executable, "-m", "earshot.daemon.cli", "--home", str(home)],
            capture_output=True,
            timeout=15,
            check=False,
        )
        assert second.returncode == 1
        assert b"already running" in second.stderr
    finally:
        stop_earshotd(first)


def test_after_a_crash_the_hook_hands_off_and_a_new_daemon_starts(home: Path) -> None:
    crashed = start_earshotd(home)
    crashed.send_signal(signal.SIGKILL)
    crashed.wait(timeout=10)
    if crashed.stderr:
        crashed.stderr.close()
    assert (home / "earshotd.sock").exists()  # left behind
    start = time.monotonic()
    assert run_hook(home, fixture("permission_request")) == b""
    assert time.monotonic() - start < 3
    proc = start_earshotd(home)
    try:
        assert run_hook(home, fixture("permission_request")) == b""
    finally:
        assert stop_earshotd(proc) == 0


# The token


def test_a_token_is_created_private(tmp_path: Path) -> None:
    path = tmp_path / "earshot" / "token"
    created = auth.ensure_token(path)
    assert len(created) == 64
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert auth.ensure_token(path) == created  # and kept


def test_a_token_others_could_read_is_replaced(tmp_path: Path) -> None:
    path = tmp_path / "token"
    first = auth.ensure_token(path)
    os.chmod(path, 0o644)  # noqa: PTH101 - mirrors a careless chmod
    second = auth.ensure_token(path)
    assert second != first
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_a_malformed_token_is_replaced(tmp_path: Path) -> None:
    path = tmp_path / "token"
    path.write_text("password123\n", encoding="ascii")
    path.chmod(0o600)
    assert len(auth.ensure_token(path)) == 64


def test_tokens_compare_exactly() -> None:
    assert auth.matches("ab" * 32, "ab" * 32)
    assert not auth.matches("ab" * 32, "ab" * 31 + "ac")


def test_paths_resolve_for_the_daemon(home: Path) -> None:
    where = paths.resolve(str(home))
    assert where.socket == home / "earshotd.sock"
