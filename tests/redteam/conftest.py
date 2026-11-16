"""The red-team suite (Phase 4, milestone 6). Every test here is an attack that must end on the
screen, or get no reply at all. One approval through any of them blocks a release."""

from __future__ import annotations

import shutil
import sys
import tempfile
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "daemon"))  # the daemon harness

from harness import RunningDaemon

from earshot.daemon.server import MAX_WAIT_S, Decider, hand_off


@pytest.fixture
def home() -> Iterator[Path]:
    path = Path(tempfile.mkdtemp(prefix="rt-"))  # short: a socket path's limit is 104 bytes
    yield path
    shutil.rmtree(path, ignore_errors=True)


@pytest.fixture
def start_daemon(home: Path) -> Iterator[Callable[..., RunningDaemon]]:
    running: list[RunningDaemon] = []

    def start(
        decider: Decider = hand_off, max_wait_s: float = MAX_WAIT_S, **kw: Any
    ) -> RunningDaemon:
        daemon = RunningDaemon(home, decider, max_wait_s, **kw)
        running.append(daemon)
        return daemon

    yield start
    for daemon in running:
        daemon.stop()


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    here = Path(__file__).parent
    for item in items:
        if Path(str(item.fspath)).parent == here:
            item.add_marker(pytest.mark.redteam)
