"""Tampering with the audit log: every edit, cut, swap and forgery is reported."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from earwarden import audit

KEY = b"k" * 32


def entry(n: int) -> dict[str, Any]:
    return {
        "id": f"req_{n:020d}",
        "session": "api",
        "tool": "Bash",
        "input_sha256": "ab" * 32,
        "input_redacted": "pytest",
        "tier": 1,
        "outcome": "handoff",
        "reason": "decided",
    }


def written(tmp_path: Path) -> tuple[Path, audit.FileAnchor]:
    store = audit.FileAnchor(tmp_path / "audit.anchor")
    log = audit.AuditLog(tmp_path / "log", KEY, store)
    for n in range(5):
        log.append(**entry(n))
    [file] = (tmp_path / "log").glob("*.jsonl")
    return file, store


def problems(file: Path, store: audit.FileAnchor) -> list[str]:
    return audit.verify(file.parent, KEY, store.load())


def test_an_outcome_rewritten_to_allow_is_caught(tmp_path: Path) -> None:
    file, store = written(tmp_path)
    lines = file.read_text().splitlines()
    record = json.loads(lines[2])
    record["outcome"] = "allow"
    lines[2] = json.dumps(record)
    file.write_text("\n".join(lines) + "\n")
    assert any("contents were changed" in p for p in problems(file, store))


def test_a_record_removed_from_the_middle_is_caught(tmp_path: Path) -> None:
    file, store = written(tmp_path)
    lines = file.read_text().splitlines()
    del lines[1]
    file.write_text("\n".join(lines) + "\n")
    assert problems(file, store) != []


def test_records_removed_from_the_end_are_caught(tmp_path: Path) -> None:
    file, store = written(tmp_path)
    lines = file.read_text().splitlines()
    file.write_text("\n".join(lines[:3]) + "\n")
    assert any("missing from the end" in p for p in problems(file, store))


def test_the_whole_log_deleted_is_caught(tmp_path: Path) -> None:
    file, store = written(tmp_path)
    file.unlink()
    assert any("missing from the end" in p for p in problems(file, store))


def test_a_forged_record_with_a_guessed_key_is_caught(tmp_path: Path) -> None:
    file, store = written(tmp_path)
    audit.AuditLog(file.parent, b"guess" * 7, store).append(**entry(9))
    assert any("contents were changed" in p for p in problems(file, store))


def test_a_record_added_with_the_real_key_but_not_by_the_daemon_is_caught(tmp_path: Path) -> None:
    file, store = written(tmp_path)
    audit.AuditLog(file.parent, KEY).append(**entry(9))
    assert any("written after the anchor" in p for p in problems(file, store))


def test_an_older_log_put_back_is_caught(tmp_path: Path) -> None:
    file, store = written(tmp_path)
    older = file.read_bytes()
    audit.AuditLog(file.parent, KEY, store).append(**entry(5))
    file.write_bytes(older)
    assert any("missing from the end" in p for p in problems(file, store))


def test_the_untouched_log_is_fine(tmp_path: Path) -> None:
    file, store = written(tmp_path)
    assert problems(file, store) == []
