"""The audit log: one JSON line per decision, in a keyed hash chain (D-025, from P-10).

Each record's `hash` is an HMAC-SHA256 over the record (without its hash) using a key the log's
writer can't see in the file: the macOS Keychain on a real install, a 0600 file in development and
tests. `prev_hash` links each record to the one before, across monthly files, so an edited,
deleted or reordered line breaks the chain.

The chain's head and length are also anchored outside the log (Phase 4, from P-10): in the
Keychain on a real install, in a 0600 file in development, beside the key. A chain alone can't
show that its newest lines were cut off, or that the whole file was swapped for an older copy;
the anchor can. `earwarden audit verify` checks both.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import subprocess
import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NamedTuple, Protocol

from pydantic import ValidationError

from earwarden import contracts, paths

KEYCHAIN_SERVICE = "dev.earwarden.audit"
ANCHOR_SERVICE = "dev.earwarden.audit.anchor"
log = logging.getLogger("earwarden.audit")


def _keychain_key() -> bytes:
    """The key from the login Keychain, created on first use."""
    account = os.environ.get("USER", "earwarden")
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
    (EARWARDEN_HOME or --home) keeps it in a 0600 file beside the token."""
    if use_keychain is None:
        use_keychain = sys.platform == "darwin" and where.config_dir == Path.home() / ".earwarden"
    return _keychain_key() if use_keychain else _file_key(where.config_dir / "audit.key")


class Anchor(NamedTuple):
    """Where the chain ended the last time Earwarden wrote to it."""

    head: str
    length: int  # how many records the chain had ("count" would shadow tuple.count)


class AnchorStore(Protocol):
    def load(self) -> Anchor | None: ...
    def save(self, anchor: Anchor) -> None: ...


def _parse_anchor(text: str) -> Anchor | None:
    head, _, count = text.strip().partition(":")
    if len(head) == 64 and count.isdigit():
        return Anchor(head, int(count))
    return None


class FileAnchor:
    """The anchor in a 0600 file, for a development home."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> Anchor | None:
        try:
            return _parse_anchor(self.path.read_text(encoding="ascii"))
        except (FileNotFoundError, UnicodeDecodeError):
            return None

    def save(self, anchor: Anchor) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fresh = self.path.with_name(self.path.name + ".new")
        fd = os.open(fresh, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="ascii") as file:
            file.write(f"{anchor.head}:{anchor.length}\n")
        fresh.replace(self.path)


class KeychainAnchor:
    """The anchor in the login Keychain, for a real install."""

    def __init__(self, account: str | None = None) -> None:
        self.account = account or os.environ.get("USER", "earwarden")

    def load(self) -> Anchor | None:
        found = subprocess.run(  # noqa: S603 - a fixed system tool and fixed arguments
            [
                "/usr/bin/security",
                "find-generic-password",
                "-s",
                ANCHOR_SERVICE,
                "-a",
                self.account,
                "-w",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        return _parse_anchor(found.stdout) if found.returncode == 0 else None

    def save(self, anchor: Anchor) -> None:
        subprocess.run(  # noqa: S603 - a fixed system tool; the value is a hash and a count
            [
                "/usr/bin/security",
                "add-generic-password",
                "-s",
                ANCHOR_SERVICE,
                "-a",
                self.account,
                "-w",
                f"{anchor.head}:{anchor.length}",
                "-U",
            ],
            capture_output=True,
            check=True,
        )


def anchor_store(where: paths.Paths, use_keychain: bool | None = None) -> AnchorStore:
    """Where the anchor lives: the Keychain on a real install, a file beside the key otherwise."""
    if use_keychain is None:
        use_keychain = sys.platform == "darwin" and where.config_dir == Path.home() / ".earwarden"
    return KeychainAnchor() if use_keychain else FileAnchor(where.config_dir / "audit.anchor")


def _digest(key: bytes, record: dict[str, Any]) -> str:
    body = {k: v for k, v in record.items() if k != "hash"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hmac.new(key, canonical.encode("ascii"), hashlib.sha256).hexdigest()


def _files(directory: Path) -> list[Path]:
    return sorted(directory.glob("*.jsonl"))


class AuditLog:
    def __init__(self, directory: Path, key: bytes, anchor: AnchorStore | None = None) -> None:
        self.directory = directory
        self.key = key
        self.anchor = anchor
        self._head = contracts.GENESIS_HASH
        self._count = 0
        for record in self.records():  # resume the chain where it ended
            head = record.get("hash")
            if isinstance(head, str):
                self._head = head
            self._count += 1
        if anchor is not None:
            saved = anchor.load()
            if saved is not None and saved != Anchor(self._head, self._count):
                log.warning(
                    "the audit log doesn't match its anchor (anchor: %d records, log: %d); "
                    "earwarden audit verify will say more",
                    saved.length,
                    self._count,
                )

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
        self._count += 1
        if self.anchor is not None:
            try:
                self.anchor.save(Anchor(self._head, self._count))
            except (OSError, subprocess.SubprocessError):
                log.exception("couldn't save the audit anchor")
        return checked


def verify(directory: Path, key: bytes, anchor: Anchor | None = None) -> list[str]:
    """Every problem in the chain, in order; an empty list means it's intact.

    With the anchor, the end of the log is checked too: records cut off the end, an older copy
    put back, or records written since the anchor was last saved.
    """
    problems: list[str] = []
    head = contracts.GENESIS_HASH
    count = 0
    hashes: list[str] = []
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
            hashes.append(head)
    if count == 0:
        problems.append("the log is empty")
    if anchor is not None:
        problems.extend(_against_anchor(anchor, hashes))
    return problems


def _against_anchor(anchor: Anchor, hashes: list[str]) -> list[str]:
    count = len(hashes)
    if count < anchor.length:
        return [
            f"{anchor.length - count} record(s) are missing from the end: the anchor saw "
            f"{anchor.length}, the log has {count}"
        ]
    if count == anchor.length:
        if hashes and hashes[-1] != anchor.head:
            return ["the end of the log isn't what the anchor saw: it was replaced"]
        return []
    if anchor.length and hashes[anchor.length - 1] != anchor.head:
        return ["the log was replaced, and written to since"]
    return [
        f"{count - anchor.length} record(s) were written after the anchor was last saved "
        "(a crash between a write and its anchor, or writing outside Earwarden)"
    ]
