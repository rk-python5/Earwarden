"""The keyed audit chain (D-025): verify catches edits, deletions and reordering."""

from __future__ import annotations

import json
import stat
from pathlib import Path
from typing import Any

import pytest
from conftest import StartDaemon
from harness import fixture, run_hook

from earshot import audit, paths
from earshot.cli import main

KEY = b"k" * 32


def entry(n: int) -> dict[str, Any]:
    return {
        "id": f"req_{n:020d}",
        "session": "api",
        "tool": "Bash",
        "input_sha256": "ab" * 32,
        "input_redacted": "pytest",
        "tier": 1,
        "outcome": "allow",
        "reason": "decided",
    }


def write_three(directory: Path) -> Path:
    log = audit.AuditLog(directory, KEY)
    for n in range(3):
        log.append(**entry(n))
    [file] = directory.glob("*.jsonl")
    return file


def test_an_untouched_chain_verifies(tmp_path: Path) -> None:
    file = write_three(tmp_path)
    assert audit.verify(tmp_path, KEY) == []
    assert stat.S_IMODE(file.stat().st_mode) == 0o600


def test_an_edited_line_is_caught(tmp_path: Path) -> None:
    file = write_three(tmp_path)
    file.write_text(file.read_text().replace('"outcome":"allow"', '"outcome":"deny"', 1))
    file.write_text(file.read_text().replace('"outcome": "allow"', '"outcome": "deny"', 1))
    assert any("changed" in p for p in audit.verify(tmp_path, KEY))


def test_a_deleted_line_is_caught(tmp_path: Path) -> None:
    file = write_three(tmp_path)
    lines = file.read_text().splitlines()
    file.write_text("\n".join([lines[0], lines[2]]) + "\n")
    assert any("doesn't follow" in p for p in audit.verify(tmp_path, KEY))


def test_reordered_lines_are_caught(tmp_path: Path) -> None:
    file = write_three(tmp_path)
    lines = file.read_text().splitlines()
    file.write_text("\n".join([lines[1], lines[0], lines[2]]) + "\n")
    assert audit.verify(tmp_path, KEY) != []


def test_a_rewritten_chain_without_the_key_is_caught(tmp_path: Path) -> None:
    """Anyone can recompute a plain hash chain; without the key the HMACs don't match."""
    write_three(tmp_path)
    assert audit.verify(tmp_path, b"x" * 32) != []


def test_the_chain_continues_after_a_restart(tmp_path: Path) -> None:
    write_three(tmp_path)
    audit.AuditLog(tmp_path, KEY).append(**entry(9))
    assert audit.verify(tmp_path, KEY) == []


def test_an_empty_log_is_reported(tmp_path: Path) -> None:
    assert audit.verify(tmp_path, KEY) == ["the log is empty"]


def test_a_development_home_keeps_its_key_in_a_private_file(tmp_path: Path) -> None:
    where = paths.resolve(str(tmp_path))
    key = audit.load_key(where)
    assert key == audit.load_key(where)
    assert stat.S_IMODE((tmp_path / "audit.key").stat().st_mode) == 0o600


def test_the_daemon_audits_every_decision_without_secrets(
    home: Path, start_daemon: StartDaemon
) -> None:
    where = paths.resolve(str(home))
    running = start_daemon(audit_log=audit.AuditLog(where.audit_dir, audit.load_key(where)))
    request = fixture("permission_request")
    request["tool_input"] = {"command": "deploy --token ghp_" + "a1B2c3D4e5" * 4}
    run_hook(home, request)
    running.wait_for(lambda d: len(d.resolved) == 1)
    running.stop()
    [record] = audit.AuditLog(where.audit_dir, audit.load_key(where)).records()
    assert (record["outcome"], record["reason"], record["tier"]) == ("handoff", "decided", 3)
    assert "ghp_" not in json.dumps(record)
    assert audit.verify(where.audit_dir, audit.load_key(where)) == []


def test_the_audit_commands(
    home: Path, start_daemon: StartDaemon, capsys: pytest.CaptureFixture[str]
) -> None:
    where = paths.resolve(str(home))
    running = start_daemon(audit_log=audit.AuditLog(where.audit_dir, audit.load_key(where)))
    run_hook(home, fixture("permission_request"))
    running.wait_for(lambda d: len(d.resolved) == 1)
    assert main(["audit", "verify", "--home", str(home)]) == 0
    assert main(["audit", "tail", "--home", str(home)]) == 0
    out = capsys.readouterr().out
    assert "intact" in out
    assert "earshot-probe: Bash -> handoff (decided)" in out
