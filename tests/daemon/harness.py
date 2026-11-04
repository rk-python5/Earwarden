"""Helpers for the daemon tests: a real daemon in a thread, and the real hook as a subprocess."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from earshot import contracts, paths
from earshot.daemon.server import Daemon, Decider
from earshot.daemon.state import Pending

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "claude_code" / "2.1.318"
HOOK_MODULE = "earshot.connectors.claude_code.hook"


def fixture(name: str) -> dict[str, Any]:
    payload = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


async def never(pending: Pending) -> contracts.Decision:
    """A decider that never answers, like a voice prompt nobody has replied to yet."""
    await asyncio.Event().wait()
    raise AssertionError("unreachable")


class RunningDaemon:
    def __init__(self, home: Path, decider: Decider, max_wait_s: float) -> None:
        self.daemon = Daemon(paths.resolve(str(home)), decider, max_wait_s)
        self.error: BaseException | None = None
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        if not self.daemon.ready.wait(timeout=10):
            raise RuntimeError(f"the daemon didn't start: {self.error!r}")

    def _run(self) -> None:
        try:
            asyncio.run(self.daemon.serve())
        except BaseException as exc:
            self.error = exc

    def stop(self) -> None:
        self.daemon.stop()
        self._thread.join(timeout=10)

    def wait_for(self, condition: Callable[[Daemon], bool], timeout: float = 10) -> None:
        deadline = time.monotonic() + timeout
        while not condition(self.daemon):
            if time.monotonic() > deadline:
                raise TimeoutError("the daemon never got there")
            time.sleep(0.01)


def start_hook(home: Path, payload: dict[str, Any], *args: str) -> subprocess.Popen[bytes]:
    proc = subprocess.Popen(
        [sys.executable, "-m", HOOK_MODULE, "--home", str(home), *args],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert proc.stdin is not None
    proc.stdin.write(json.dumps(payload).encode())
    proc.stdin.close()
    return proc


def finish(proc: subprocess.Popen[bytes], timeout: float = 15) -> bytes:
    """What the hook printed. It must have exited 0 with nothing on stderr."""
    returncode = proc.wait(timeout=timeout)
    assert proc.stdout is not None
    assert proc.stderr is not None
    out, err = proc.stdout.read(), proc.stderr.read()
    proc.stdout.close()
    proc.stderr.close()
    assert (returncode, err) == (0, b"")
    return out


def run_hook(home: Path, payload: dict[str, Any], *args: str) -> bytes:
    return finish(start_hook(home, payload, *args))
