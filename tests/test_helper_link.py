"""The daemon's link to the signed helper (Phase 2, milestone 7), with a fake helper."""

from __future__ import annotations

import asyncio
import base64
import json
import shutil
import struct
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from earshot.voice.helper import HelperLink

TOKEN = "ab" * 32


@pytest.fixture
def short() -> Iterator[Path]:
    # Not pytest's tmp_path: Unix socket paths must stay under 104 bytes on macOS.
    path = Path(tempfile.mkdtemp(prefix="eh-"))
    yield path
    shutil.rmtree(path, ignore_errors=True)


async def connect(
    path: Path, token: str = TOKEN
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    reader, writer = await asyncio.open_unix_connection(str(path))
    writer.write((json.dumps({"hello": "earshot-motion", "v": 1, "token": token}) + "\n").encode())
    await writer.drain()
    return reader, writer


async def until(condition: object, seconds: float = 2.0) -> None:
    for _ in range(int(seconds / 0.01)):
        if callable(condition) and condition():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("timed out")


def test_the_helper_streams_audio_motion_and_devices(short: Path) -> None:
    async def scenario() -> None:
        link = HelperLink(short / "helper.sock", TOKEN)
        heard: list[bytes] = []
        link.on_audio = heard.append
        await link.start()
        reader, writer = await connect(link.socket_path)
        await until(lambda: link.connected)
        assert json.loads(await reader.readline()) == {"mic": False, "motion": False}
        samples = struct.pack("<4h", 0, 1000, -1000, 32767)
        for message in (
            {"audio": base64.b64encode(samples).decode()},
            {"motion": [12.5, 0.1, -0.2, 1.4]},
            {"devices": {"output": "rehaan's AirPods", "input": "rehaan's AirPods"}},
            {"permission": {"mic": "granted"}},
            "not an object",
        ):
            writer.write((json.dumps(message) + "\n").encode())
        writer.write(b"{broken json\n")
        await writer.drain()
        await until(lambda: link.permission)
        assert heard == [samples]
        assert link.motion[-1] == (12.5, 0.1, -0.2, 1.4)
        assert link.devices["output"] == "rehaan's AirPods"
        link.want(mic=True, motion=True)
        assert json.loads(await reader.readline()) == {"mic": True, "motion": True}
        writer.close()
        await until(lambda: not link.connected)
        await link.stop()

    asyncio.run(scenario())


def test_a_helper_without_the_token_is_refused(short: Path) -> None:
    async def scenario() -> None:
        link = HelperLink(short / "helper.sock", TOKEN)
        await link.start()
        reader, writer = await connect(link.socket_path, token="cd" * 32)
        assert await reader.read() == b""  # closed without a word
        assert not link.connected
        writer.close()
        await writer.wait_closed()
        await link.stop()

    asyncio.run(scenario())


def test_a_reconnecting_helper_is_told_what_is_wanted(short: Path) -> None:
    async def scenario() -> None:
        link = HelperLink(short / "helper.sock", TOKEN)
        await link.start()
        link.want(mic=True)
        reader, writer = await connect(link.socket_path)
        assert json.loads(await reader.readline()) == {"mic": True, "motion": False}
        writer.close()
        await link.stop()

    asyncio.run(scenario())
