"""earshot-hook: the command hook Claude Code runs for Earshot. Standard library only.

    earshot-hook [--home DIR] [--wait SECONDS] [--event]

Claude Code passes one hook payload as JSON on stdin.

- **PermissionRequest:** the hook sends an ApprovalRequest to the daemon over its Unix socket,
  waits for a Decision, and prints Claude Code's allow or deny object. A hand-off prints nothing.
- **SessionStart, SessionEnd, Stop, Notification and PostToolUse:** the hook passes the event on
  and doesn't wait. With `--event` it never waits, whatever the payload says.

Whatever happens, the hook exits 0 and prints nothing but that one decision object:

- Printing nothing hands the request to Claude Code's own dialog, so every error, doubt or
  timeout ends on the screen. Silence never approves.
- Exit code 2 isn't honoured on PermissionRequest, and on Stop it would keep Claude running.
- On SessionStart, anything printed would become Claude's context.

Flags are read by hand, because argparse exits 2 on a bad flag. Unknown arguments are ignored.
"""

from __future__ import annotations

import json
import os
import signal
import socket
import sys
import time
from pathlib import Path
from typing import Any, BinaryIO, NamedTuple

from earshot import paths, wire

# `earshot init` gives the hook Claude Code's 300 s timeout. Stop just short of it, so the hook
# always ends on its own terms (D-020).
WAIT_LIMIT_S = 290.0
CONNECT_TIMEOUT_S = 2.0
EVENT_TIMEOUT_S = 0.5

MAX_SHORT_CHARS = 200
MAX_STOP_MESSAGE_CHARS = 4000
MAX_NOTIFICATION_CHARS = 2000
DECISION_KEYS = {"v", "id", "outcome", "message", "tier"}


class Options(NamedTuple):
    home: str | None
    wait_s: float
    event_only: bool


class TerminatedError(Exception):
    """Claude Code ended the hook: SIGTERM after No or Esc (D-020)."""


def parse_args(argv: list[str]) -> Options:
    home: str | None = None
    wait_s = WAIT_LIMIT_S
    event_only = False
    rest = iter(argv)
    for arg in rest:
        if arg == "--event":
            event_only = True
        elif arg == "--home":
            home = next(rest, None) or None
        elif arg == "--wait":
            try:
                value = float(next(rest, ""))
            except ValueError:
                continue
            if 0 <= value <= WAIT_LIMIT_S:  # also rejects NaN
                wait_s = value
    return Options(home, wait_s, event_only)


def read_token(path: Path) -> str | None:
    try:
        with path.open(encoding="ascii") as file:
            token = file.read(256).strip()
    except (OSError, UnicodeDecodeError):
        return None
    if 32 <= len(token) <= 128 and all(c in "0123456789abcdef" for c in token):
        return token
    return None


def _text(payload: dict[str, Any], key: str, limit: int = MAX_SHORT_CHARS) -> str | None:
    """A non-empty string field, or None if it's missing, empty, not a string or too long."""
    value = payload.get(key)
    if isinstance(value, str) and 0 < len(value) <= limit:
        return value
    return None


def _clipped(payload: dict[str, Any], key: str, limit: int) -> str | None:
    """A free-text field, cut to `limit` characters."""
    value = payload.get(key)
    if isinstance(value, str) and value:
        return value[:limit]
    return None


def build_request(payload: dict[str, Any], token: str, received_s: float) -> dict[str, Any] | None:
    """The ApprovalRequest for a PermissionRequest payload, or None if it can't be built."""
    session_id = _text(payload, "session_id")
    tool_name = _text(payload, "tool_name")
    cwd = _text(payload, "cwd", 4096)
    tool_input = payload.get("tool_input")
    if not (session_id and tool_name and cwd and cwd.startswith("/")):
        return None
    if not isinstance(tool_input, dict):
        return None
    request: dict[str, Any] = {
        "v": wire.PROTOCOL_VERSION,
        "id": wire.new_request_id(),
        "token": token,
        "source": "claude_code",
        "session_id": session_id,
        "cwd": cwd,
        "permission_mode": _text(payload, "permission_mode") or "unknown",
        "tool_name": tool_name,
        "tool_input": tool_input,
        "received_at": wire.utc_timestamp(received_s),
    }
    prompt_id = _text(payload, "prompt_id")
    if prompt_id:
        request["prompt_id"] = prompt_id
    return request


def build_event(payload: dict[str, Any], token: str) -> dict[str, Any] | None:
    """The Event for a lifecycle payload, or None if Earshot doesn't use it."""
    name = payload.get("hook_event_name")
    session_id = _text(payload, "session_id")
    if name not in wire.EVENTS or not session_id:
        return None
    event: dict[str, Any] = {
        "v": wire.PROTOCOL_VERSION,
        "token": token,
        "source": "claude_code",
        "event": name,
        "session_id": session_id,
    }
    fields: dict[str, str | None] = {
        "cwd": _text(payload, "cwd", 4096),
        "prompt_id": _text(payload, "prompt_id"),
    }
    if name == "SessionStart":
        fields["session_source"] = _text(payload, "source")
        fields["model"] = _text(payload, "model")
    elif name == "SessionEnd":
        fields["reason"] = _text(payload, "reason")
    elif name == "Stop":
        fields["last_assistant_message"] = _clipped(
            payload, "last_assistant_message", MAX_STOP_MESSAGE_CHARS
        )
    elif name == "Notification":
        fields["notification_type"] = _text(payload, "notification_type")
        fields["message"] = _clipped(payload, "message", MAX_NOTIFICATION_CHARS)
    elif name == "PostToolUse":
        tool_name = _text(payload, "tool_name")
        if not tool_name or "tool_input" not in payload:
            return None
        fields["tool_name"] = tool_name
        fields["tool_use_id"] = _text(payload, "tool_use_id")
        fields["input_sha256"] = wire.input_sha256(payload["tool_input"])
    if fields["cwd"] is not None and not fields["cwd"].startswith("/"):
        fields["cwd"] = None
    event.update({key: value for key, value in fields.items() if value is not None})
    return event


def read_line(conn: socket.socket, deadline: float) -> bytes | None:
    """One newline-terminated reply, or None if it doesn't arrive whole and in time."""
    data = b""
    while b"\n" not in data:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or len(data) > wire.MAX_REPLY_BYTES:
            return None
        conn.settimeout(remaining)
        chunk = conn.recv(4096)
        if not chunk:
            return None
        data += chunk
    line = data.split(b"\n", 1)[0]
    return line if len(line) <= wire.MAX_REPLY_BYTES else None


def ask_daemon(socket_path: str, request: dict[str, Any], wait_s: float) -> bytes | None:
    line = wire.encode(request)
    if len(line) > wire.MAX_REQUEST_BYTES:
        return None
    deadline = time.monotonic() + wait_s
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.settimeout(min(CONNECT_TIMEOUT_S, max(wait_s, 0.001)))
        conn.connect(socket_path)
        conn.settimeout(max(deadline - time.monotonic(), 0.001))
        conn.sendall(line)
        return read_line(conn, deadline)


def tell_daemon(socket_path: str, event: dict[str, Any]) -> None:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.settimeout(EVENT_TIMEOUT_S)
        conn.connect(socket_path)
        conn.sendall(wire.encode(event))


def decision_output(reply: bytes | None, request_id: str) -> str | None:
    """Claude Code's decision object for a valid reply, or None for anything else."""
    if reply is None:
        return None
    try:
        decision = json.loads(reply)
    except ValueError:
        return None
    if not isinstance(decision, dict) or not set(decision) <= DECISION_KEYS:
        return None
    version = decision.get("v")
    if type(version) is not int or version != wire.PROTOCOL_VERSION:  # true and 1.0 aren't 1
        return None
    if decision.get("id") != request_id:
        return None
    tier = decision.get("tier")
    if tier is not None and (type(tier) is not int or not 0 <= tier <= 3):
        return None
    outcome = decision.get("outcome")
    message = decision.get("message")
    if outcome == "allow" and message is None:
        body: dict[str, str] = {"behavior": "allow"}
    elif outcome == "deny" and message is None:
        body = {"behavior": "deny", "message": wire.DEFAULT_DENY_MESSAGE}
    elif (
        outcome == "deny"
        and isinstance(message, str)
        and 0 < len(message) <= wire.MAX_DENY_MESSAGE_CHARS
    ):
        body = {"behavior": "deny", "message": message}
    else:  # a hand-off, an unknown outcome, or a message where none belongs
        return None
    return json.dumps(
        {"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": body}}
    )


def run(argv: list[str], stdin: BinaryIO) -> str | None:
    """Everything the hook does. Returns what to print, if anything; may raise."""
    options = parse_args(argv)
    raw = stdin.read(wire.MAX_REQUEST_BYTES + 1)
    received_s = time.time()
    if len(raw) > wire.MAX_REQUEST_BYTES:
        return None
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        return None
    where = paths.resolve(options.home)
    token = read_token(where.token)
    if token is None:
        return None
    if payload.get("hook_event_name") == "PermissionRequest" and not options.event_only:
        request = build_request(payload, token, received_s)
        if request is None:
            return None
        reply = ask_daemon(str(where.socket), request, options.wait_s)
        return decision_output(reply, request["id"])
    event = build_event(payload, token)
    if event is not None:
        tell_daemon(str(where.socket), event)
    return None


def _stop(signum: int, frame: object) -> None:
    raise TerminatedError


def main() -> None:
    """The console entry point. It never returns: it always ends with exit status 0."""
    try:
        for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            signal.signal(signum, _stop)
        output = run(sys.argv[1:], sys.stdin.buffer)
        if output:
            sys.stdout.write(output)
            sys.stdout.flush()
    except BaseException:  # noqa: S110 - nothing may escape a hook; silence hands off
        pass
    # Skip interpreter shutdown, so a stdout that Claude Code has closed can't change the status.
    os._exit(0)


if __name__ == "__main__":
    main()
