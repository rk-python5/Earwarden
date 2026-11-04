"""The wire helpers that the hook and the daemon share, and where Earshot keeps its files."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

from earshot import paths, wire


def test_a_message_is_one_ascii_line() -> None:
    line = wire.encode({"message": "nein, später\nbitte"})
    assert line.endswith(b"\n")
    assert line.count(b"\n") == 1
    assert line.isascii()
    assert json.loads(line) == {"message": "nein, später\nbitte"}


def test_lone_surrogates_dont_break_encoding() -> None:
    weird = json.loads('{"command": "echo \\ud800"}')
    assert wire.encode(weird).isascii()
    assert len(wire.input_sha256(weird)) == 64


def test_the_fingerprint_ignores_key_order_but_not_values() -> None:
    a = {"command": "git push", "description": "push"}
    b = {"description": "push", "command": "git push"}
    assert wire.input_sha256(a) == wire.input_sha256(b)
    assert wire.input_sha256(a) != wire.input_sha256({**a, "command": "git push -f"})


def test_request_ids_are_unique_and_well_formed() -> None:
    ids = {wire.new_request_id() for _ in range(1000)}
    assert len(ids) == 1000
    assert all(re.fullmatch(r"req_[0-9a-f]{20}", i) for i in ids)


@pytest.mark.parametrize(
    ("moment", "expected"),
    [
        (0.0, "1970-01-01T00:00:00.000Z"),
        (1793795321.4355, "2026-11-04T12:28:41.435Z"),
        (1793795321.9999, "2026-11-04T12:28:41.999Z"),
    ],
)
def test_timestamps(moment: float, expected: str) -> None:
    assert wire.utc_timestamp(moment) == expected


def test_one_home_holds_everything(tmp_path: Path) -> None:
    where = paths.resolve(str(tmp_path))
    assert where.token == tmp_path / "token"
    assert where.config == tmp_path / "config.toml"
    assert where.socket == tmp_path / "earshotd.sock"
    assert where.audit_dir == tmp_path / "audit"


def test_the_environment_sets_the_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(paths.HOME_ENV, str(tmp_path))
    assert paths.resolve().socket == tmp_path / "earshotd.sock"
    assert paths.resolve("/elsewhere").socket == Path("/elsewhere/earshotd.sock")


def test_the_plans_defaults(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv(paths.HOME_ENV, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(sys, "platform", "darwin")
    where = paths.resolve()
    assert where.token == tmp_path / ".earshot" / "token"
    assert (
        where.socket == tmp_path / "Library" / "Application Support" / "Earshot" / "earshotd.sock"
    )
