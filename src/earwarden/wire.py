"""The wire format between Earwarden's clients and its daemon. Standard library only.

`earwarden-hook` imports this module, and the hook may use only the standard library (CLAUDE.md,
"The hook client is minimal"). Each message is one line of JSON over the daemon's Unix socket.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any

PROTOCOL_VERSION = 1

# A tool input can be a whole file (Write), so a request may run to a few MiB. Anything bigger
# can't be summarised by voice anyway and is handed to the screen.
MAX_REQUEST_BYTES = 8 * 1024 * 1024
MAX_REPLY_BYTES = 64 * 1024

# What you say after "no", passed to the agent as the deny message.
MAX_DENY_MESSAGE_CHARS = 2000
DEFAULT_DENY_MESSAGE = "Denied by voice in Earwarden."

OUTCOMES = ("allow", "deny", "handoff")
EVENTS = ("SessionStart", "SessionEnd", "Stop", "Notification", "PostToolUse")
SOURCES = ("claude_code", "python_api")


def encode(message: dict[str, Any]) -> bytes:
    """One message as one line. ASCII-only, so encoding can't fail on odd characters."""
    return json.dumps(message, separators=(",", ":"), ensure_ascii=True).encode("ascii") + b"\n"


def canonical_json(value: Any) -> bytes:
    """The same bytes for the same value: sorted keys, no spaces, ASCII escapes."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "ascii"
    )


def input_sha256(tool_input: Any) -> str:
    """The fingerprint of a tool input. It ties a PostToolUse event back to the waiting request
    (D-020), and it's the audit log's `input_sha256`."""
    return hashlib.sha256(canonical_json(tool_input)).hexdigest()


def new_request_id() -> str:
    return "req_" + os.urandom(10).hex()


def utc_timestamp(epoch_s: float | None = None) -> str:
    """ISO 8601 in UTC with milliseconds, such as 2026-11-03T10:15:02.114Z."""
    moment = time.time() if epoch_s is None else epoch_s
    whole = int(moment)
    millis = min(int((moment - whole) * 1000), 999)
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(whole)) + f".{millis:03d}Z"
