"""The `earwarden` command's client: how long it waits for the daemon's reply."""

from __future__ import annotations

import contextlib
import socket
import threading
from pathlib import Path

import pytest

from earwarden import paths, wire
from earwarden.daemon import client


def _answer_after(server: socket.socket, delay: float, ready: threading.Event) -> None:
    ready.set()
    conn, _ = server.accept()
    with conn:
        conn.recv(4096)
        threading.Event().wait(delay)
        reply = {"v": wire.PROTOCOL_VERSION, "ok": True, "text": "done"}
        with contextlib.suppress(OSError):  # the client may have given up by now
            conn.sendall(wire.encode(reply))


def _where(tmp_path: Path) -> paths.Paths:
    return paths.resolve(str(tmp_path))


def _serve(where: paths.Paths, delay: float) -> socket.socket:
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(where.socket))
    server.listen(1)
    ready = threading.Event()
    threading.Thread(target=_answer_after, args=(server, delay, ready), daemon=True).start()
    ready.wait(2)
    return server


@pytest.mark.parametrize(("command", "waits"), [("status", False), ("mode", False), ("talk", True)])
def test_only_talk_waits_longer_than_a_status_reply(
    home: Path, monkeypatch: pytest.MonkeyPatch, command: str, waits: bool
) -> None:
    monkeypatch.setattr(client, "TIMEOUT_S", 0.2)
    monkeypatch.setattr(client, "TALK_TIMEOUT_S", 3.0)
    where = _where(home)
    server = _serve(where, delay=0.6)
    try:
        reply = client.send(where, command, "quiet" if command == "mode" else None)
    finally:
        server.close()
    assert (reply is not None) is waits
    if reply is not None:
        assert reply.text == "done"
