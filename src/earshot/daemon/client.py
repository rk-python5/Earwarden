"""The `earshot` command's side of a Command to the running daemon (Phase 4, milestone 2).

`earshot mode`, `earshot status` and `earshot talk` send one Command line over the daemon's
socket, with the same token the hook uses, and read one reply. A command only changes what
Earshot announces; it can't answer a request.
"""

from __future__ import annotations

import socket
from typing import Any

from pydantic import ValidationError

from earshot import auth, contracts, paths, wire

TIMEOUT_S = 5.0


def send(where: paths.Paths, command: str, arg: str | None = None) -> contracts.CommandReply | None:
    """The daemon's reply, or None if it isn't running or didn't answer."""
    if not where.socket.exists():
        return None
    message: dict[str, Any] = {
        "v": wire.PROTOCOL_VERSION,
        "token": auth.ensure_token(where.token),
        "source": "python_api",
        "command": command,
    }
    if arg is not None:
        message["arg"] = arg
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
            conn.settimeout(TIMEOUT_S)
            conn.connect(str(where.socket))
            conn.sendall(wire.encode(message))
            data = b""
            while b"\n" not in data and len(data) <= wire.MAX_REPLY_BYTES:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                data += chunk
    except OSError:
        return None
    line = data.split(b"\n", 1)[0]
    try:
        return contracts.CommandReply.model_validate_json(line)
    except (ValueError, ValidationError):
        return None
