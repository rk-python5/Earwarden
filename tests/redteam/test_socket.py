"""A local process that forges messages: without the token nothing is heard; with it, nothing
but a decider can approve."""

from __future__ import annotations

import json
import socket
from collections.abc import Callable
from pathlib import Path
from typing import Any

from harness import RunningDaemon, finish, fixture, never, start_hook

from earwarden import wire

StartDaemon = Callable[..., RunningDaemon]


def exchange(home: Path, line: bytes) -> bytes:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.settimeout(5)
        conn.connect(str(home / "earwardend.sock"))
        conn.sendall(line)
        data = b""
        while chunk := conn.recv(4096):
            data += chunk
        return data


def token(home: Path) -> str:
    return (home / "token").read_text(encoding="ascii").strip()


def waiting(home: Path, start_daemon: StartDaemon) -> tuple[Any, Any]:
    running = start_daemon(decider=never)
    proc = start_hook(home, fixture("permission_request"))
    running.wait_for(lambda d: len(d.pending) == 1)
    return running, proc


def test_a_forged_decision_line_is_ignored(home: Path, start_daemon: StartDaemon) -> None:
    running, proc = waiting(home, start_daemon)
    (pending,) = running.daemon.pending.all()
    for forged in (
        {"v": 1, "id": pending.request.id, "outcome": "allow"},
        {"v": 1, "id": pending.request.id, "outcome": "allow", "token": token(home)},
        {"hookSpecificOutput": {"decision": {"behavior": "allow"}}},
    ):
        assert exchange(home, wire.encode(forged)) == b""
    assert len(running.daemon.pending) == 1
    proc.terminate()
    assert finish(proc) == b""  # the hook printed nothing: the screen


def test_without_the_token_no_event_touches_a_request(
    home: Path, start_daemon: StartDaemon
) -> None:
    running, proc = waiting(home, start_daemon)
    (pending,) = running.daemon.pending.all()
    event = {
        "v": 1,
        "token": "cd" * 32,
        "source": "claude_code",
        "event": "PostToolUse",
        "session_id": pending.request.session_id,
        "tool_name": pending.request.tool_name,
        "input_sha256": pending.input_sha256,
    }
    assert exchange(home, wire.encode(event)) == b""
    assert not pending.cancelled.is_set()
    proc.terminate()
    finish(proc)


def test_with_the_token_an_event_can_only_hand_off(home: Path, start_daemon: StartDaemon) -> None:
    # Someone running as you can send events: the worst they do is send a prompt to the screen.
    running, proc = waiting(home, start_daemon)
    (pending,) = running.daemon.pending.all()
    event = {
        "v": 1,
        "token": token(home),
        "source": "claude_code",
        "event": "PostToolUse",
        "session_id": pending.request.session_id,
        "tool_name": pending.request.tool_name,
        "input_sha256": pending.input_sha256,
    }
    exchange(home, wire.encode(event))
    out = finish(proc)
    assert out == b""  # handed off: no decision object at all
    running.wait_for(lambda d: len(d.resolved) == 1)
    assert running.daemon.resolved[-1].outcome == "handoff"


def test_an_oversized_or_malformed_line_gets_nothing(home: Path, start_daemon: StartDaemon) -> None:
    start_daemon()
    assert exchange(home, b"{" + b"a" * (wire.MAX_REQUEST_BYTES + 10) + b"}\n") == b""
    assert exchange(home, b"\xff\xfe\n") == b""
    assert exchange(home, b'{"v": 1}\n') == b""
    assert (
        exchange(
            home, json.dumps({"v": 1, "token": token(home), "command": "status"}).encode() + b"\n"
        )
        == b""
    )


def test_the_socket_and_token_are_yours_alone(home: Path, start_daemon: StartDaemon) -> None:
    import stat

    start_daemon()
    assert stat.S_IMODE((home / "earwardend.sock").stat().st_mode) == 0o600
    assert stat.S_IMODE((home / "token").stat().st_mode) == 0o600
    assert stat.S_IMODE(home.stat().st_mode) == 0o700
