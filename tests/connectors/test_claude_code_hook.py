"""earwarden-hook against a stand-in daemon, run as a real subprocess the way Claude Code runs it.

Every case checks the hook's two promises: it exits 0 with nothing on stderr, and the only thing
it ever prints is one valid decision object for a PermissionRequest. The payloads were captured
from Claude Code 2.1.318 on rehaan's Mac during Step 0.
"""

from __future__ import annotations

import json
import shutil
import signal
import socket
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from earwarden import contracts, wire
from earwarden.connectors.claude_code import hook

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "claude_code" / "2.1.318"
HOOK_MODULE = "earwarden.connectors.claude_code.hook"
TOKEN = "0123456789abcdef" * 4
HANG = b"hang"  # the stand-in keeps the connection open and never answers

Reply = Callable[[dict[str, Any]], bytes | None]


def fixture(name: str) -> dict[str, Any]:
    payload = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def decide(outcome: str, **extra: Any) -> Reply:
    def reply(message: dict[str, Any]) -> bytes:
        return wire.encode({"v": 1, "id": message["id"], "outcome": outcome, **extra})

    return reply


class StubDaemon:
    """A daemon stand-in on a real Unix socket. It records each message and answers per test."""

    def __init__(self, socket_path: Path, reply: Reply) -> None:
        self.received: list[dict[str, Any]] = []
        self.got_message = threading.Event()
        self._reply = reply
        self._held: list[socket.socket] = []
        self._server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server.bind(str(socket_path))
        self._server.listen(8)
        self._server.settimeout(0.1)
        self._stopping = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        while not self._stopping.is_set():
            try:
                conn, _ = self._server.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            self._handle(conn)

    def _handle(self, conn: socket.socket) -> None:
        held = False
        try:
            conn.settimeout(5)
            data = b""
            while b"\n" not in data:
                chunk = conn.recv(1 << 16)
                if not chunk:
                    return
                data += chunk
            message = json.loads(data.split(b"\n", 1)[0])
            self.received.append(message)
            self.got_message.set()
            answer = self._reply(message)
            if answer == HANG:
                self._held.append(conn)
                held = True
            elif answer is not None:
                conn.sendall(answer)
        except OSError:  # the hook hung up first, as it does on an oversized reply
            pass
        finally:
            if not held:
                conn.close()

    def close(self) -> None:
        self._stopping.set()
        self._thread.join(timeout=2)
        self._server.close()
        for conn in self._held:
            conn.close()


@pytest.fixture
def home() -> Iterator[Path]:
    # Not pytest's tmp_path: Unix socket paths must stay under 104 bytes on macOS.
    path = Path(tempfile.mkdtemp(prefix="eh-"))
    (path / "token").write_text(TOKEN + "\n", encoding="ascii")
    yield path
    shutil.rmtree(path, ignore_errors=True)


@pytest.fixture
def daemon(home: Path) -> Iterator[Callable[[Reply], StubDaemon]]:
    started: list[StubDaemon] = []

    def start(reply: Reply) -> StubDaemon:
        stub = StubDaemon(home / "earwardend.sock", reply)
        started.append(stub)
        return stub

    yield start
    for stub in started:
        stub.close()


def run_hook(
    home: Path, payload: dict[str, Any] | bytes, *args: str, timeout: float = 15
) -> subprocess.CompletedProcess[bytes]:
    data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    result = subprocess.run(
        [sys.executable, "-m", HOOK_MODULE, "--home", str(home), *args],
        input=data,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    assert result.returncode == 0
    assert result.stderr == b""
    return result


def printed(result: subprocess.CompletedProcess[bytes]) -> Any:
    return json.loads(result.stdout)


# Decisions


def test_allow_prints_claude_codes_allow_object(
    home: Path, daemon: Callable[[Reply], StubDaemon]
) -> None:
    daemon(decide("allow"))
    result = run_hook(home, fixture("permission_request"))
    assert printed(result) == {
        "hookSpecificOutput": {
            "hookEventName": "PermissionRequest",
            "decision": {"behavior": "allow"},
        }
    }


def test_deny_passes_the_spoken_message_to_the_agent(
    home: Path, daemon: Callable[[Reply], StubDaemon]
) -> None:
    daemon(decide("deny", message="use poetry instead", tier=1))
    result = run_hook(home, fixture("permission_request"))
    decision = printed(result)["hookSpecificOutput"]["decision"]
    assert decision == {"behavior": "deny", "message": "use poetry instead"}


def test_a_bare_deny_gets_a_default_message(
    home: Path, daemon: Callable[[Reply], StubDaemon]
) -> None:
    daemon(decide("deny"))
    decision = printed(run_hook(home, fixture("permission_request")))["hookSpecificOutput"]
    assert decision["decision"] == {"behavior": "deny", "message": wire.DEFAULT_DENY_MESSAGE}


def test_a_handoff_prints_nothing(home: Path, daemon: Callable[[Reply], StubDaemon]) -> None:
    daemon(decide("handoff", tier=3))
    assert run_hook(home, fixture("permission_request")).stdout == b""


def test_the_request_matches_the_contract(
    home: Path, daemon: Callable[[Reply], StubDaemon]
) -> None:
    stub = daemon(decide("handoff"))
    payload = fixture("permission_request")
    run_hook(home, payload)
    [message] = stub.received
    request = contracts.ApprovalRequest.model_validate_json(json.dumps(message))
    assert request.token == TOKEN
    assert request.source == "claude_code"
    assert request.session_id == payload["session_id"]
    assert request.prompt_id == payload["prompt_id"]
    assert request.cwd == payload["cwd"]
    assert request.permission_mode == "default"
    assert request.tool_name == "Bash"
    assert request.tool_input == payload["tool_input"]


BAD_REPLIES: dict[str, Reply] = {
    "wrong id": lambda m: wire.encode({"v": 1, "id": "req_0000000000", "outcome": "allow"}),
    "version 2": lambda m: wire.encode({"v": 2, "id": m["id"], "outcome": "allow"}),
    "version as a boolean": lambda m: wire.encode({"v": True, "id": m["id"], "outcome": "allow"}),
    "version as a float": lambda m: wire.encode({"v": 1.0, "id": m["id"], "outcome": "allow"}),
    "no version": lambda m: wire.encode({"id": m["id"], "outcome": "allow"}),
    "unknown outcome": decide("maybe"),
    "message on allow": decide("allow", message="sure"),
    "message on handoff": decide("handoff", message="later"),
    "empty deny message": decide("deny", message=""),
    "deny message too long": decide("deny", message="x" * (wire.MAX_DENY_MESSAGE_CHARS + 1)),
    "unknown field": decide("allow", approve_everything=True),
    "tier as text": decide("allow", tier="1"),
    "tier out of range": decide("allow", tier=4),
    "tier as a boolean": decide("allow", tier=True),
    "not json": lambda m: b"allow\n",
    "a list": lambda m: b'["allow"]\n',
    "no newline before close": lambda m: wire.encode({"v": 1, "id": m["id"], "outcome": "allow"})[
        :-1
    ],
    "too long": lambda m: b'{"pad": "' + b"x" * (wire.MAX_REPLY_BYTES + 10) + b'"}\n',
    "closed without a reply": lambda m: None,
}


@pytest.mark.parametrize("reply", BAD_REPLIES.values(), ids=BAD_REPLIES.keys())
def test_anything_but_a_valid_decision_hands_off(
    home: Path, daemon: Callable[[Reply], StubDaemon], reply: Reply
) -> None:
    daemon(reply)
    assert run_hook(home, fixture("permission_request")).stdout == b""


# Fail-safe paths


def test_no_daemon_hands_off_at_once(home: Path) -> None:
    start = time.monotonic()
    assert run_hook(home, fixture("permission_request")).stdout == b""
    assert time.monotonic() - start < 3


@pytest.mark.parametrize("token", [None, "", "not-a-hex-token", "abc123"])
def test_a_missing_or_bad_token_hands_off_without_connecting(
    home: Path, daemon: Callable[[Reply], StubDaemon], token: str | None
) -> None:
    stub = daemon(decide("allow"))
    if token is None:
        (home / "token").unlink()
    else:
        (home / "token").write_text(token, encoding="ascii")
    assert run_hook(home, fixture("permission_request")).stdout == b""
    assert stub.received == []


def _without(key: str) -> bytes:
    payload = fixture("permission_request")
    del payload[key]
    return json.dumps(payload).encode()


def _with(key: str, value: Any) -> bytes:
    payload = fixture("permission_request")
    payload[key] = value
    return json.dumps(payload).encode()


BAD_INPUTS = {
    "not json": b"permission please",
    "empty": b"",
    "a list": b"[]",
    "no session": _without("session_id"),
    "no tool name": _without("tool_name"),
    "no tool input": _without("tool_input"),
    "tool input not an object": _with("tool_input", "touch probe-1.txt"),
    "relative cwd": _with("cwd", "earwarden-probe"),
    "empty session id": _with("session_id", ""),
    "huge tool name": _with("tool_name", "x" * 500),
}


@pytest.mark.parametrize("payload", BAD_INPUTS.values(), ids=BAD_INPUTS.keys())
def test_bad_input_hands_off_without_connecting(
    home: Path, daemon: Callable[[Reply], StubDaemon], payload: bytes
) -> None:
    stub = daemon(decide("allow"))
    assert run_hook(home, payload).stdout == b""
    assert stub.received == []


def test_oversized_input_hands_off(home: Path, daemon: Callable[[Reply], StubDaemon]) -> None:
    stub = daemon(decide("allow"))
    payload = fixture("permission_request")
    payload["tool_input"] = {"content": "x" * wire.MAX_REQUEST_BYTES}
    assert run_hook(home, payload).stdout == b""
    assert stub.received == []


def test_a_silent_daemon_hands_off_when_the_wait_ends(
    home: Path, daemon: Callable[[Reply], StubDaemon]
) -> None:
    daemon(lambda m: HANG)
    start = time.monotonic()
    assert run_hook(home, fixture("permission_request"), "--wait", "1").stdout == b""
    assert 0.9 < time.monotonic() - start < 5


def test_sigterm_while_waiting_exits_0_and_prints_nothing(
    home: Path, daemon: Callable[[Reply], StubDaemon]
) -> None:
    """Claude Code sends SIGTERM when you press No or Esc in its dialog (D-020)."""
    stub = daemon(lambda m: HANG)
    proc = subprocess.Popen(
        [sys.executable, "-m", HOOK_MODULE, "--home", str(home)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert proc.stdin is not None
    proc.stdin.write(json.dumps(fixture("permission_request")).encode())
    proc.stdin.close()
    assert stub.got_message.wait(timeout=10)
    proc.send_signal(signal.SIGTERM)
    returncode = proc.wait(timeout=10)
    assert proc.stdout is not None
    assert proc.stderr is not None
    assert (returncode, proc.stdout.read(), proc.stderr.read()) == (0, b"", b"")
    proc.stdout.close()
    proc.stderr.close()


def test_unknown_flags_are_ignored(home: Path, daemon: Callable[[Reply], StubDaemon]) -> None:
    daemon(decide("allow"))
    result = run_hook(home, fixture("permission_request"), "--frobnicate", "--wait")
    assert printed(result)["hookSpecificOutput"]["decision"] == {"behavior": "allow"}


# Events


EVENT_FIELDS = {
    "session_start": {"event": "SessionStart", "session_source": "startup"},
    "session_end": {"event": "SessionEnd", "reason": "prompt_input_exit"},
    "stop": {"event": "Stop"},
    "notification_permission_prompt": {
        "event": "Notification",
        "notification_type": "permission_prompt",
        "message": "Claude needs your permission",
    },
    "post_tool_use": {
        "event": "PostToolUse",
        "tool_name": "Bash",
        "tool_use_id": "toolu_01Rd9TeCcw49YvMzxy2NGJR7",
    },
}


@pytest.mark.parametrize("name", EVENT_FIELDS)
def test_events_are_passed_on_and_nothing_is_printed(
    home: Path, daemon: Callable[[Reply], StubDaemon], name: str
) -> None:
    stub = daemon(lambda m: None)  # events get no reply
    payload = fixture(name)
    assert run_hook(home, payload, "--event").stdout == b""
    assert stub.got_message.wait(timeout=5)  # the hook doesn't wait for the daemon to read it
    [message] = stub.received
    event = contracts.Event.model_validate_json(json.dumps(message))
    assert event.token == TOKEN
    assert event.session_id == payload["session_id"]
    assert event.prompt_id == payload.get("prompt_id")
    for key, value in EVENT_FIELDS[name].items():
        assert getattr(event, key) == value


def test_post_tool_use_carries_the_fingerprint_of_its_request() -> None:
    """On rehaan's run, the PostToolUse for a request had the same tool input (D-020)."""
    session = [
        json.loads(line)
        for line in (FIXTURES / "probe_session.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    prompt = fixture("permission_request")["prompt_id"]
    by_event = {
        r["event"]: r["payload"] for r in session if r["payload"].get("prompt_id") == prompt
    }
    event = hook.build_event(by_event["PostToolUse"], TOKEN)
    assert event is not None
    assert event["input_sha256"] == wire.input_sha256(by_event["PermissionRequest"]["tool_input"])


def test_an_edits_post_tool_use_names_the_file_it_changed() -> None:
    """The daemon needs it for P-01's rule: once conftest.py changes, running code needs more."""
    payload = fixture("post_tool_use")
    payload["tool_name"] = "Edit"
    payload["tool_input"] = {"file_path": "/Users/rehaan/code/api/conftest.py", "old_string": "a"}
    event = hook.build_event(payload, TOKEN)
    assert event is not None
    assert event["file_path"] == "/Users/rehaan/code/api/conftest.py"
    contracts.Event.model_validate_json(json.dumps(event))
    assert "file_path" not in (hook.build_event(fixture("post_tool_use"), TOKEN) or {})


def test_event_mode_never_answers_a_permission_request(
    home: Path, daemon: Callable[[Reply], StubDaemon]
) -> None:
    stub = daemon(decide("allow"))
    assert run_hook(home, fixture("permission_request"), "--event").stdout == b""
    assert stub.received == []


def test_events_dont_wait_for_the_daemon(home: Path, daemon: Callable[[Reply], StubDaemon]) -> None:
    daemon(lambda m: HANG)
    start = time.monotonic()
    run_hook(home, fixture("stop"), "--event")
    assert time.monotonic() - start < 3


def test_events_earwarden_doesnt_use_are_dropped(
    home: Path, daemon: Callable[[Reply], StubDaemon]
) -> None:
    stub = daemon(decide("allow"))
    run_hook(home, fixture("pre_tool_use"), "--event")
    assert stub.received == []


def test_long_texts_are_clipped() -> None:
    payload = fixture("stop")
    payload["last_assistant_message"] = "x" * 10_000
    event = hook.build_event(payload, TOKEN)
    assert event is not None
    assert len(event["last_assistant_message"]) == hook.MAX_STOP_MESSAGE_CHARS
    contracts.Event.model_validate_json(json.dumps(event))


# Arguments


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        ([], hook.Options(None, hook.WAIT_LIMIT_S, False)),
        (["--event"], hook.Options(None, hook.WAIT_LIMIT_S, True)),
        (["--home", "/x", "--wait", "5"], hook.Options("/x", 5.0, False)),
        (["--wait", "nan"], hook.Options(None, hook.WAIT_LIMIT_S, False)),
        (["--wait", "-1"], hook.Options(None, hook.WAIT_LIMIT_S, False)),
        (["--wait", "1e9"], hook.Options(None, hook.WAIT_LIMIT_S, False)),
        (["--wait", "soon"], hook.Options(None, hook.WAIT_LIMIT_S, False)),
        (["--home"], hook.Options(None, hook.WAIT_LIMIT_S, False)),
    ],
)
def test_arguments(argv: list[str], expected: hook.Options) -> None:
    assert hook.parse_args(argv) == expected


# Imports and speed


def test_the_hook_imports_only_the_standard_library() -> None:
    code = (
        "import sys\n"
        "before = set(sys.modules)\n"
        f"import {HOOK_MODULE}\n"
        "print('\\n'.join(sorted(set(sys.modules) - before)))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    roots = {name.split(".")[0] for name in result.stdout.split()}
    assert roots - set(sys.stdlib_module_names) == {"earwarden"}
    loaded = {name for name in result.stdout.split() if name.startswith("earwarden")}
    assert loaded == {
        "earwarden",
        "earwarden.connectors",
        "earwarden.connectors.claude_code",
        HOOK_MODULE,
        "earwarden.paths",
        "earwarden.wire",
    }


def test_the_console_script_works(home: Path, daemon: Callable[[Reply], StubDaemon]) -> None:
    daemon(decide("allow"))
    script = Path(sys.executable).parent / "earwarden-hook"
    result = subprocess.run(
        [str(script), "--home", str(home)],
        input=json.dumps(fixture("permission_request")).encode(),
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert (result.returncode, result.stderr) == (0, b"")
    assert printed(result)["hookSpecificOutput"]["decision"] == {"behavior": "allow"}


def test_round_trip_time(home: Path, daemon: Callable[[Reply], StubDaemon]) -> None:
    """The plan budgets 80 ms for hook start plus the socket round trip; this measures it.

    Run `uv run pytest tests/connectors -k round_trip -s` to see the numbers. The bound here
    only catches something badly wrong, like a heavy import.
    """
    daemon(decide("allow"))
    payload = json.dumps(fixture("permission_request")).encode()
    timings = []
    for _ in range(10):
        start = time.perf_counter()
        result = run_hook(home, payload)
        timings.append((time.perf_counter() - start) * 1000)
        assert result.stdout
    median = statistics.median(timings)
    print(f"\nearwarden-hook round trip: median {median:.0f} ms, max {max(timings):.0f} ms")
    assert median < 1000
