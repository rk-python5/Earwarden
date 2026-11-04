"""The audit log: one JSON line per decision, in a keyed hash chain (D-025, from P-10).

Each record's `hash` is an HMAC-SHA256 over the record (without its hash) using a key the log's
writer can't see in the file: the macOS Keychain on a real install, a 0600 file in development and
tests. `prev_hash` links each record to the one before, across monthly files, so an edited,
deleted or reordered line breaks the chain. Cutting off the newest lines can only be caught once
the head is anchored outside the file, in Phase 4.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import subprocess
import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from earshot import contracts, paths

KEYCHAIN_SERVICE = "dev.earshot.audit"


def _keychain_key() -> bytes:
    """The key from the login Keychain, created on first use."""
    account = os.environ.get("USER", "earshot")
    found = subprocess.run(  # noqa: S603 - a fixed system tool and fixed arguments
        ["/usr/bin/security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", account, "-w"],
        capture_output=True,
        text=True,
        check=False,
    )
    if found.returncode == 0 and found.stdout.strip():
        return bytes.fromhex(found.stdout.strip())
    key = secrets.token_hex(32)
    subprocess.run(  # noqa: S603 - a fixed system tool; the key comes from secrets
        [
            "/usr/bin/security",
            "add-generic-password",
            "-s",
            KEYCHAIN_SERVICE,
            "-a",
            account,
            "-w",
            key,
            "-U",
        ],
        capture_output=True,
        check=True,
    )
    return bytes.fromhex(key)


def _file_key(path: Path) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        return bytes.fromhex(path.read_text(encoding="ascii").strip())
    except (FileNotFoundError, ValueError):
        pass
    key = secrets.token_hex(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="ascii") as file:
        file.write(key + "\n")
    return bytes.fromhex(key)


def load_key(where: paths.Paths, use_keychain: bool | None = None) -> bytes:
    """The chain's key. A real install on macOS keeps it in the Keychain; a development home
    (EARSHOT_HOME or --home) keeps it in a 0600 file beside the token."""
    if use_keychain is None:
        use_keychain = sys.platform == "darwin" and where.config_dir == Path.home() / ".earshot"
    return _keychain_key() if use_keychain else _file_key(where.config_dir / "audit.key")


def _digest(key: bytes, record: dict[str, Any]) -> str:
    body = {k: v for k, v in record.items() if k != "hash"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hmac.new(key, canonical.encode("ascii"), hashlib.sha256).hexdigest()


def _files(directory: Path) -> list[Path]:
    return sorted(directory.glob("*.jsonl"))


class AuditLog:
    def __init__(self, directory: Path, key: bytes) -> None:
        self.directory = directory
        self.key = key
        self._head = contracts.GENESIS_HASH
        for record in self.records():  # resume the chain where it ended
            head = record.get("hash")
            if isinstance(head, str):
                self._head = head

    def records(self) -> Iterator[dict[str, Any]]:
        for file in _files(self.directory):
            for line in file.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    try:
                        yield json.loads(line)
                    except ValueError:
                        yield {"_unreadable": line}

    def append(self, **fields: Any) -> contracts.AuditRecord:
        now = datetime.now(UTC)
        record = {
            "v": 1,
            "ts": now.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            **fields,
            "prev_hash": self._head,
        }
        record["hash"] = _digest(self.key, record)
        checked = contracts.AuditRecord.model_validate_json(json.dumps(record))
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        line = (json.dumps(record, ensure_ascii=True) + "\n").encode("ascii")
        fd = os.open(
            self.directory / f"{now:%Y-%m}.jsonl", os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600
        )
        try:
            os.write(fd, line)
        finally:
            os.close(fd)
        self._head = record["hash"]
        return checked


def verify(directory: Path, key: bytes) -> list[str]:
    """Every problem in the chain, in order; an empty list means it's intact."""
    problems: list[str] = []
    head = contracts.GENESIS_HASH
    count = 0
    for file in _files(directory):
        for number, line in enumerate(file.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            count += 1
            where = f"{file.name} line {number}"
            try:
                record = json.loads(line)
                contracts.AuditRecord.model_validate_json(line)
            except (ValueError, ValidationError):
                problems.append(f"{where}: not a valid audit record")
                continue
            if record["prev_hash"] != head:
                problems.append(f"{where}: doesn't follow the record before it (deleted or moved)")
            if not hmac.compare_digest(record["hash"], _digest(key, record)):
                problems.append(f"{where}: its contents were changed")
            head = record["hash"]
    if count == 0:
        problems.append("the log is empty")
    return problems
