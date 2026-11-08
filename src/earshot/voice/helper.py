"""The daemon's end of the link to the signed helper, earshot-motion (Phase 2, milestone 7).

The helper is a small Swift app that owns the macOS plumbing (D-016, D-023):

- It captures the AirPods mic, so the mic permission belongs to it, granted once in its own name,
  instead of to whichever Python runs the daemon.
- It reports device changes, such as the AirPods connecting or the output switching.
- It streams head motion from Core Motion, for nods and shakes (`gestures`).

It connects to a Unix socket the daemon serves (`helper.sock`, readable only by your user) and
proves itself with the same token the hook uses. Messages are JSON lines both ways:

    helper to daemon  {"hello": "earshot-motion", "v": 1, "token": "..."}   first, once
                      {"audio": "<base64 16-bit samples, 16 kHz mono>"}    while the mic is on
                      {"motion": [t, x, y, z]}                              while motion is on
                      {"devices": {"output": "...", "input": "...", "headset": true}}
                      {"permission": {"mic": "granted", "motion": "denied"}}
    daemon to helper  {"mic": true}  {"motion": false}

The daemon asks for the mic and motion only while an approval is being asked, so the AirPods stay
in their better-sounding mode the rest of the time. Without a helper, the daemon falls back to
capturing the mic itself (Phase 1's way).
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hmac
import json
import logging
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any

from earshot.voice.gestures import Sample

log = logging.getLogger("earshot.helper")

HELLO_TIMEOUT_S = 5.0
MAX_LINE = 64 * 1024
MOTION_KEPT = 50 * 30  # 30 seconds at 50 Hz


class HelperLink:
    def __init__(self, socket_path: Path, token: str) -> None:
        self.socket_path = socket_path
        self.token = token
        self.on_audio: Callable[[bytes], None] | None = None  # 16-bit samples, 16 kHz mono
        self.motion: deque[Sample] = deque(maxlen=MOTION_KEPT)
        self.devices: dict[str, Any] = {}
        self.permission: dict[str, str] = {}
        self._writer: asyncio.StreamWriter | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._server: asyncio.AbstractServer | None = None
        self._wanted: dict[str, bool] = {"mic": False, "motion": False}

    @property
    def connected(self) -> bool:
        return self._writer is not None and not self._writer.is_closing()

    async def start(self) -> None:
        from earshot.daemon.server import open_socket

        self._loop = asyncio.get_running_loop()
        sock = open_socket(self.socket_path)
        self._server = await asyncio.start_unix_server(self._serve, sock=sock, limit=MAX_LINE)
        log.info("waiting for the helper on %s", self.socket_path)

    async def stop(self) -> None:
        if self._writer is not None:
            self._writer.close()
        if self._server is not None:
            self._server.close()
        with contextlib.suppress(FileNotFoundError):
            self.socket_path.unlink()

    def want(self, **flags: bool) -> None:
        """Ask the helper to turn the mic or motion on or off. Safe to call from any thread."""
        self._wanted.update(flags)
        if self._loop is not None and self.connected:
            self._loop.call_soon_threadsafe(self._send, flags)

    def _send(self, message: dict[str, Any]) -> None:
        if self._writer is not None and not self._writer.is_closing():
            self._writer.write((json.dumps(message) + "\n").encode())

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            line = await asyncio.wait_for(reader.readline(), HELLO_TIMEOUT_S)
            hello = json.loads(line)
            if not isinstance(hello, dict):
                raise ValueError("not a hello")
            token = hello.get("token")
            if (
                hello.get("hello") != "earshot-motion"
                or not isinstance(token, str)
                or not hmac.compare_digest(token, self.token)
            ):
                log.warning("refused a helper connection without the right token")
                writer.close()
                return
        except (TimeoutError, ValueError, ConnectionError, asyncio.LimitOverrunError):
            writer.close()
            return
        if self._writer is not None:
            self._writer.close()  # a newer helper replaces the old one
        self._writer = writer
        log.info("helper connected (v%s)", hello.get("v"))
        self._send(dict(self._wanted))  # catch it up on what's wanted now
        try:
            while line := await reader.readline():
                self._handle(line)
        except (ValueError, ConnectionError, asyncio.LimitOverrunError):
            log.warning("the helper sent something unreadable; dropping it")
        finally:
            if self._writer is writer:
                self._writer = None
                log.info("helper disconnected")
            writer.close()

    def _handle(self, line: bytes) -> None:
        try:
            message = json.loads(line)
        except ValueError:
            return
        if not isinstance(message, dict):
            return
        if isinstance(audio := message.get("audio"), str) and self.on_audio is not None:
            try:
                self.on_audio(base64.b64decode(audio, validate=True))
            except ValueError:
                return
        elif isinstance(motion := message.get("motion"), list) and len(motion) == 4:
            try:
                self.motion.append(Sample(*(float(v) for v in motion)))
            except (TypeError, ValueError):
                return
        elif isinstance(devices := message.get("devices"), dict):
            self.devices = devices
            log.info("devices: output %s, input %s", devices.get("output"), devices.get("input"))
        elif isinstance(permission := message.get("permission"), dict):
            self.permission = {str(k): str(v) for k, v in permission.items()}
            log.info("helper permissions: %s", self.permission)
