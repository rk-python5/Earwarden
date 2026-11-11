"""Launching the signed helper (Phase 2, milestone 7), and its link off the daemon's loop."""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from earshot.daemon.server import AlreadyRunningError
from earshot.voice import helper

TOKEN = "ab" * 32


@pytest.fixture
def short() -> Iterator[Path]:
    # Not pytest's tmp_path: Unix socket paths must stay under 104 bytes on macOS.
    path = Path(tempfile.mkdtemp(prefix="eh-"))
    yield path
    shutil.rmtree(path, ignore_errors=True)


def test_the_helper_is_given_absolute_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `open -a` reads a relative path as an app's name, and the helper starts in `/`.
    ran: list[list[str]] = []

    def run(command: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        ran.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.chdir(tmp_path)
    problem = helper.launch(
        "build/EarshotMotion.app", Path("home/helper.sock"), Path("home/token"), "AirPods"
    )
    assert problem is None
    (command,) = ran
    here = tmp_path.resolve()
    assert command[command.index("-a") + 1] == str(here / "build" / "EarshotMotion.app")
    assert command[command.index("--socket") + 1] == str(here / "home" / "helper.sock")
    assert command[command.index("--token-file") + 1] == str(here / "home" / "token")


def test_a_helper_that_wont_open_says_why(monkeypatch: pytest.MonkeyPatch) -> None:
    def run(command: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 1, "", "Unable to find application\n")

    monkeypatch.setattr(subprocess, "run", run)
    problem = helper.launch("gone.app", Path("helper.sock"), Path("token"), "AirPods")
    assert problem == "Unable to find application"


def test_a_command_can_hold_the_link_on_its_own_thread(short: Path) -> None:
    # `earshot enroll --helper`: the command blocks on the mic while the link's loop runs beside it.
    thread = helper.LinkThread(helper.HelperLink(short / "helper.sock", TOKEN))
    thread.start()
    assert not thread.wait(0.1)  # no helper yet

    async def fake_helper() -> dict[str, Any]:
        reader, writer = await asyncio.open_unix_connection(str(short / "helper.sock"))
        for message in (
            {"hello": "earshot-motion", "v": 1, "token": TOKEN},
            {"devices": {"output": "AirPods", "input": "AirPods", "headset": True}},
        ):
            writer.write((json.dumps(message) + "\n").encode())
        await writer.drain()
        assert json.loads(await reader.readline()) == {"mic": False, "motion": False}
        while not thread.link.devices:
            await asyncio.sleep(0.01)
        thread.link.want(mic=True)  # from another thread than the link's loop
        wanted: dict[str, Any] = json.loads(await reader.readline())
        writer.close()
        await writer.wait_closed()
        return wanted

    assert asyncio.run(asyncio.wait_for(fake_helper(), 5)) == {"mic": True}
    assert thread.link.devices["output"] == "AirPods"
    assert not thread.allowed(0.1)  # the helper never said it may use the mic
    thread.link.permission["mic"] = "granted"
    assert thread.allowed(0.1)
    thread.stop()
    assert not (short / "helper.sock").exists()


def test_the_link_wont_start_beside_a_running_daemon(short: Path) -> None:
    first = helper.LinkThread(helper.HelperLink(short / "helper.sock", TOKEN))
    first.start()
    second = helper.LinkThread(helper.HelperLink(short / "helper.sock", TOKEN))
    with pytest.raises(AlreadyRunningError):
        second.start()
    first.stop()
