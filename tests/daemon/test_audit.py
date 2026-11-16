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


# The anchor (Phase 4, milestone 5; P-10's second half)


def anchored(directory: Path) -> tuple[audit.AuditLog, audit.FileAnchor]:
    store = audit.FileAnchor(directory / "audit.anchor")
    log = audit.AuditLog(directory / "log", KEY, store)
    for n in range(3):
        log.append(**entry(n))
    return log, store


def test_the_anchor_follows_every_write_in_a_private_file(tmp_path: Path) -> None:
    _, store = anchored(tmp_path)
    saved = store.load()
    assert saved is not None
    assert saved.length == 3
    assert stat.S_IMODE((tmp_path / "audit.anchor").stat().st_mode) == 0o600
    [file] = (tmp_path / "log").glob("*.jsonl")
    assert saved.head == json.loads(file.read_text().splitlines()[-1])["hash"]
    assert audit.verify(tmp_path / "log", KEY, saved) == []


def test_records_cut_off_the_end_are_caught(tmp_path: Path) -> None:
    _, store = anchored(tmp_path)
    [file] = (tmp_path / "log").glob("*.jsonl")
    lines = file.read_text().splitlines()
    file.write_text("\n".join(lines[:-1]) + "\n")
    assert audit.verify(tmp_path / "log", KEY) == []  # the chain alone can't tell
    [problem] = audit.verify(tmp_path / "log", KEY, store.load())
    assert problem == "1 record(s) are missing from the end: the anchor saw 3, the log has 2"
    file.write_text("")
    assert "3 record(s) are missing" in audit.verify(tmp_path / "log", KEY, store.load())[-1]


def test_an_older_copy_put_back_is_caught(tmp_path: Path) -> None:
    log, store = anchored(tmp_path)
    [file] = (tmp_path / "log").glob("*.jsonl")
    older = file.read_bytes()
    log.append(**entry(7))
    file.write_bytes(older)  # three records again, but not the three the anchor saw
    assert audit.verify(tmp_path / "log", KEY) == []
    assert audit.verify(tmp_path / "log", KEY, store.load()) == [
        "1 record(s) are missing from the end: the anchor saw 4, the log has 3"
    ]
    stray = audit.AuditLog(tmp_path / "log", KEY)  # and written to, without the anchor
    stray.append(**entry(8))
    stray.append(**entry(9))
    [problem] = audit.verify(tmp_path / "log", KEY, store.load())
    assert problem == "the log was replaced, and written to since"


def test_a_record_written_without_the_anchor_is_caught(tmp_path: Path) -> None:
    # Someone with the key can extend the chain; the anchor shows the daemon didn't.
    _, store = anchored(tmp_path)
    audit.AuditLog(tmp_path / "log", KEY).append(**entry(9))
    assert audit.verify(tmp_path / "log", KEY) == []
    [problem] = audit.verify(tmp_path / "log", KEY, store.load())
    assert problem.startswith("1 record(s) were written after the anchor was last saved")


def test_the_end_replaced_with_the_same_count_is_caught(tmp_path: Path) -> None:
    _, store = anchored(tmp_path)
    [file] = (tmp_path / "log").glob("*.jsonl")
    lines = file.read_text().splitlines()
    file.write_text("\n".join(lines[:-1]) + "\n")
    audit.AuditLog(tmp_path / "log", KEY).append(**entry(5))  # a different third record
    assert audit.verify(tmp_path / "log", KEY) == []
    assert audit.verify(tmp_path / "log", KEY, store.load()) == [
        "the end of the log isn't what the anchor saw: it was replaced"
    ]


def test_a_restart_continues_the_anchor_and_a_mismatch_is_logged(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    _, store = anchored(tmp_path)
    audit.AuditLog(tmp_path / "log", KEY, store).append(**entry(4))
    assert store.load() == audit.Anchor(store.load().head, 4)  # type: ignore[union-attr]
    assert audit.verify(tmp_path / "log", KEY, store.load()) == []
    [file] = (tmp_path / "log").glob("*.jsonl")
    file.write_text("\n".join(file.read_text().splitlines()[:-2]) + "\n")
    with caplog.at_level("WARNING", logger="earshot.audit"):
        audit.AuditLog(tmp_path / "log", KEY, store)
    assert "doesn't match its anchor (anchor: 4 records, log: 2)" in caplog.text


def test_the_daemon_and_the_commands_use_the_anchor(
    home: Path, start_daemon: StartDaemon, capsys: pytest.CaptureFixture[str]
) -> None:
    where = paths.resolve(str(home))
    store = audit.anchor_store(where)
    assert isinstance(store, audit.FileAnchor)
    running = start_daemon(audit_log=audit.AuditLog(where.audit_dir, audit.load_key(where), store))
    run_hook(home, fixture("permission_request"))
    running.wait_for(lambda d: len(d.resolved) == 1)
    assert main(["audit", "verify", "--home", str(home)]) == 0
    assert "matches its anchor (1 records)" in capsys.readouterr().out
    [file] = where.audit_dir.glob("*.jsonl")
    file.write_text("")
    assert main(["audit", "verify", "--home", str(home)]) == 1
    assert "missing from the end" in capsys.readouterr().out


def test_an_unreadable_anchor_is_no_anchor(tmp_path: Path) -> None:
    store = audit.FileAnchor(tmp_path / "audit.anchor")
    assert store.load() is None
    (tmp_path / "audit.anchor").write_text("garbage")
    assert store.load() is None
    (tmp_path / "audit.anchor").write_text("ab" * 32 + ":12\n")
    assert store.load() == audit.Anchor("ab" * 32, 12)
