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
                      {"log": "mic on: 16000 Hz, 1 channel(s)"}             for the daemon's log
                      {"button": "stem"}                                     a press, with --stem
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
import subprocess
import threading
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any

from earshot.voice.gestures import Sample

log = logging.getLogger("earshot.helper")

HELLO_TIMEOUT_S = 5.0
MAX_LINE = 64 * 1024
MOTION_KEPT = 50 * 30  # 30 seconds at 50 Hz
MAX_NOTE = 200  # of a helper's log line


class HelperLink:
    def __init__(self, socket_path: Path, token: str) -> None:
        self.socket_path = socket_path
        self.token = token
        self.on_audio: Callable[[bytes], None] | None = None  # 16-bit samples, 16 kHz mono
        self.on_button: Callable[[str], None] | None = None  # "stem": push-to-talk (D-032)
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
            self.permission.update({str(k): str(v) for k, v in permission.items()})
            log.info("helper permissions: %s", self.permission)
        elif isinstance(note := message.get("log"), str):
            log.info("helper: %s", note[:MAX_NOTE])
        elif isinstance(button := message.get("button"), str):
            log.info("button: %s", button[:MAX_NOTE])
            if self.on_button is not None:
                self.on_button(button[:MAX_NOTE])


def launch(
    app: str | Path, socket_path: Path, token_file: Path, headset: str, stem: bool = False
) -> str | None:
    """Open the helper app through Launch Services, so macOS asks for the mic in its name.

    Returns what went wrong, or None. Every path is made absolute: `open -a` takes a relative
    path for an app's name, and the helper starts in `/`, not in the caller's folder. A helper
    that's already running isn't started again; it reconnects to the same socket by itself.
    """
    command = [
        "/usr/bin/open",
        "-g",
        "-a",
        str(Path(app).expanduser().resolve()),
        "--args",
        "--socket",
        str(socket_path.resolve()),
        "--token-file",
        str(token_file.resolve()),
        "--headset",
        headset,
    ]
    if stem:
        command.append("--stem")
    result = subprocess.run(command, capture_output=True, text=True, check=False)  # noqa: S603
    return None if result.returncode == 0 else result.stderr.strip() or "open failed"


class LinkThread:
    """A HelperLink on an event loop of its own, for commands that aren't the daemon.

    `earshot enroll` records through the helper this way, so a voiceprint is made on the same
    channel the daemon later checks it on.
    """

    def __init__(self, link: HelperLink) -> None:
        self.link = link
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)

    def start(self) -> None:
        """Serve the helper's socket. Raises AlreadyRunningError if earshotd is serving it."""
        self._thread.start()
        try:
            asyncio.run_coroutine_threadsafe(self.link.start(), self._loop).result(timeout=5)
        except BaseException:
            self._end()
            raise

    def wait(self, seconds: float = 10.0) -> bool:
        """Whether the helper connected and reported its devices within `seconds`."""
        end = time.monotonic() + seconds
        while time.monotonic() < end and not (self.link.connected and self.link.devices):
            time.sleep(0.05)
        return self.link.connected

    def allowed(self, seconds: float = 60.0) -> bool:
        """Whether the helper may use the mic, waiting while macOS's prompt is answered."""
        end = time.monotonic() + seconds
        while time.monotonic() < end and self.link.permission.get("mic") == "not asked":
            time.sleep(0.1)
        return self.link.permission.get("mic") == "granted"

    def stop(self) -> None:
        self.link.want(mic=False, motion=False)
        asyncio.run_coroutine_threadsafe(self.link.stop(), self._loop).result(timeout=5)
        self._end()

    def _end(self) -> None:
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5)
        pending = asyncio.all_tasks(self._loop)  # the connection's reader, if a helper was there
        for task in pending:
            task.cancel()
        if pending:
            self._loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        self._loop.close()
