"""The shared token every client presents to the daemon.

The token lives in a file only you can read (mode 0600). A client that can read it is running as
you; the daemon compares tokens in constant time.
"""

from __future__ import annotations

import hmac
import os
import secrets
import stat
from pathlib import Path

TOKEN_BYTES = 32  # 64 hex characters


def _readable_only_by_owner(path: Path) -> bool:
    info = path.stat()
    return info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) & 0o077 == 0


def ensure_token(path: Path) -> str:
    """The token in `path`, created if it's missing.

    A token that others could have read is replaced, since it may no longer be secret.
    """
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        if _readable_only_by_owner(path):
            token = path.read_text(encoding="ascii").strip()
            if len(token) == 2 * TOKEN_BYTES and all(c in "0123456789abcdef" for c in token):
                return token
    except (FileNotFoundError, UnicodeDecodeError):
        pass
    token = secrets.token_hex(TOKEN_BYTES)
    fresh = path.with_name(path.name + ".new")
    fresh.unlink(missing_ok=True)
    fd = os.open(fresh, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="ascii") as file:
        file.write(token + "\n")
    fresh.replace(path)  # atomic, so a hook never reads half a token
    return token


def matches(given: str, expected: str) -> bool:
    return hmac.compare_digest(given.encode(), expected.encode())
