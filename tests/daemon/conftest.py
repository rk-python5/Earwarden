"""Fixtures for the daemon tests: a short home folder and a daemon starter."""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from harness import RunningDaemon

from earshot.audit import AuditLog
from earshot.daemon.floor import Floor
from earshot.daemon.server import MAX_WAIT_S, Decider, hand_off


@pytest.fixture
def home() -> Iterator[Path]:
    # Not pytest's tmp_path: Unix socket paths must stay under 104 bytes on macOS.
    path = Path(tempfile.mkdtemp(prefix="ed-"))
    yield path
    shutil.rmtree(path, ignore_errors=True)


StartDaemon = Callable[..., RunningDaemon]


@pytest.fixture
def start_daemon(home: Path) -> Iterator[StartDaemon]:
    running: list[RunningDaemon] = []

    def start(
        decider: Decider = hand_off,
        max_wait_s: float = MAX_WAIT_S,
        observe: bool = False,
        audit_log: AuditLog | None = None,
        floor: Floor | None = None,
    ) -> RunningDaemon:
        daemon = RunningDaemon(home, decider, max_wait_s, observe, audit_log, floor)
        running.append(daemon)
        return daemon

    yield start
    for daemon in running:
        daemon.stop()
