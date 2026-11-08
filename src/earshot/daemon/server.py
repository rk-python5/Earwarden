"""earshotd's socket server: requests in, decisions out (Phase 1, milestone 2).

One asyncio process listens on a Unix socket that only you can reach: mode 0600 in a folder with
mode 0700, and no network port. Every message is one line of JSON and carries the shared token.
A message that fails its contract or the token check gets no reply, so the hook prints nothing
and Claude Code's own dialog takes over.

A PermissionRequest waits for whichever comes first:

- the decider's answer (for now always a hand-off; the voice path comes in milestone 6)
- the hook going away, because you pressed No or Esc in Claude Code's dialog (D-020)
- a cancellation: the tool ran, so you approved it on screen (D-020), the session ended, or the
  daemon is stopping
- the wait limit, just inside the hook's own
"""

from __future__ import annotations

import asyncio
import collections
import contextlib
import json
import logging
import os
import socket
import stat
import threading
import time
from collections.abc import Awaitable, Callable
from pathlib import Path, PurePosixPath

from pydantic import ValidationError

from earshot import audit, auth, contracts, paths, wire
from earshot.daemon.state import Pending, PendingRequests, Resolved, Session, Sessions
from earshot.narrator import redact
from earshot.policy import engine, places

log = logging.getLogger("earshot.daemon")

READ_TIMEOUT_S = 5.0  # a client must send its line promptly
MAX_WAIT_S = 280.0  # inside the hook's 290 s, which is inside Claude Code's 300 s
SHUTDOWN_GRACE_S = 2.0
HISTORY = 500

Decider = Callable[[Pending], Awaitable[contracts.Decision]]


class AlreadyRunningError(RuntimeError):
    """Another daemon answers on the socket."""


def decision(pending: Pending, outcome: contracts.Outcome) -> contracts.Decision:
    return contracts.Decision(v=wire.PROTOCOL_VERSION, id=pending.request.id, outcome=outcome)


async def hand_off(pending: Pending) -> contracts.Decision:
    """Milestone 2's decider: everything goes to the screen."""
    return decision(pending, "handoff")


def open_socket(path: Path) -> socket.socket:
    """A listening socket at `path` that only this user can reach.

    A socket left behind by a crashed daemon is replaced; a live daemon is left alone.
    """
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    if path.exists() or path.is_symlink():
        if not stat.S_ISSOCK(path.lstat().st_mode):
            raise AlreadyRunningError(f"{path} exists and isn't a socket; not touching it")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
            probe.settimeout(1.0)
            try:
                probe.connect(str(path))
            except OSError:
                path.unlink(missing_ok=True)  # stale, from a daemon that didn't shut down
            else:
                raise AlreadyRunningError(f"earshotd is already running on {path}")
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.bind(str(path))
        path.chmod(0o600)
        sock.listen(64)
    except BaseException:
        sock.close()
        raise
    sock.setblocking(False)
    return sock


def parse(line: bytes) -> contracts.ApprovalRequest | contracts.Event | None:
    """The message on one line, or None if it isn't a valid one."""
    try:
        peek = json.loads(line)
        if not isinstance(peek, dict):
            return None
        if "event" in peek:
            return contracts.Event.model_validate_json(line)
        return contracts.ApprovalRequest.model_validate_json(line)
    except (ValueError, ValidationError):
        return None


class Daemon:
    def __init__(
        self,
        where: paths.Paths,
        decider: Decider = hand_off,
        max_wait_s: float = MAX_WAIT_S,
        observe: bool = False,
        audit_log: audit.AuditLog | None = None,
    ) -> None:
        self.where = where
        self.decider = decider
        self.max_wait_s = max_wait_s
        self.observe = observe
        self.audit_log = audit_log
        self.sessions = Sessions()
        self.pending = PendingRequests()
        self.resolved: collections.deque[Resolved] = collections.deque(maxlen=HISTORY)
        self.ready = threading.Event()  # set once the socket is listening
        self._token = ""
        self._stopping: asyncio.Event | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._handlers: set[asyncio.Task[None]] = set()

    async def serve(self) -> None:
        """Listen until `stop()`, then hand every waiting request to the screen."""
        self._loop = asyncio.get_running_loop()
        self._stopping = asyncio.Event()
        self._token = auth.ensure_token(self.where.token)
        sock = open_socket(self.where.socket)
        server = await asyncio.start_unix_server(
            self._on_connection, sock=sock, limit=wire.MAX_REQUEST_BYTES + 4096
        )
        log.info("listening on %s", self.where.socket)
        self.ready.set()
        try:
            async with server:
                try:
                    await self._stopping.wait()
                finally:
                    # Stop accepting, but keep the server open while connections already
                    # accepted finish: in Python 3.11, closing it mid-accept drops the new
                    # connection without closing its socket.
                    with contextlib.suppress(OSError, ValueError):
                        self._loop.remove_reader(sock.fileno())
                    for pending in self.pending.all():
                        pending.cancel("shutdown")
                    await self._finish_connections()
        finally:
            with contextlib.suppress(FileNotFoundError):
                self.where.socket.unlink()
            log.info("stopped")

    async def _finish_connections(self) -> None:
        """Let every connection already accepted finish, up to the grace period.

        Accepting takes asyncio a few steps before a handler exists, so a connection that
        arrived just before the stop may have no handler yet. Waiting on all of the daemon's
        other tasks, until none are left, lets those finish too.
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + SHUTDOWN_GRACE_S
        while True:
            others = {task for task in asyncio.all_tasks() if task is not asyncio.current_task()}
            remaining = deadline - loop.time()
            if not others or remaining <= 0:
                return
            await asyncio.wait(others, timeout=remaining)

    def stop(self) -> None:
        """Ask a running daemon to stop. Safe from any thread, and any number of times."""
        loop, stopping = self._loop, self._stopping
        if loop is None or stopping is None or loop.is_closed():
            return
        with contextlib.suppress(RuntimeError):  # the loop closed after the check
            loop.call_soon_threadsafe(stopping.set)

    async def _on_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        task = asyncio.current_task()
        if task is not None:
            self._handlers.add(task)
        try:
            await self._handle(reader, writer)
        finally:
            if task is not None:
                self._handlers.discard(task)
            writer.close()
            with contextlib.suppress(OSError):
                await writer.wait_closed()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            line = await asyncio.wait_for(reader.readline(), READ_TIMEOUT_S)
        except (TimeoutError, ValueError, OSError):  # slow, oversized, or gone
            return
        if not line.endswith(b"\n"):
            return
        message = parse(line)
        if message is None:
            log.warning("ignored a message that isn't a valid version-1 request or event")
            return
        if not auth.matches(message.token, self._token):
            log.warning("ignored a message with the wrong token")
            return
        if isinstance(message, contracts.Event):
            self._on_event(message)
            return
        await self._on_request(message, reader, writer)

    def _on_event(self, event: contracts.Event) -> None:
        if event.event == "SessionEnd":
            self.sessions.end(event.session_id)
            for pending in self.pending.for_session(event.session_id):
                pending.cancel("session_ended")
            return
        session = self.sessions.seen(event.session_id, event.cwd)
        if event.event == "SessionStart" and event.model:
            session.model = event.model
        elif event.event == "Stop" and event.last_assistant_message:
            session.last_message = event.last_assistant_message
        elif event.event == "PostToolUse":
            if event.file_path and PurePosixPath(event.file_path).name in places.CONFIG_FILES:
                session.config_edited = True
            answered = self.pending.answered_by(event)
            if answered is not None:
                answered.cancel("tool_ran")

    async def _on_request(
        self,
        request: contracts.ApprovalRequest,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        session = self.sessions.seen(request.session_id, request.cwd)
        pending = Pending(request, wire.input_sha256(request.tool_input), session)
        if self._stopping is not None and self._stopping.is_set():
            pending.cancel("shutdown")  # arrived as the daemon stops: straight to the screen
        self.pending.add(pending)
        log.info("request %s: %s in %s", request.id, request.tool_name, session.name)
        if self.observe:
            self._observe(request, session)

        decide = asyncio.ensure_future(self._decide(pending))
        hook_gone = asyncio.ensure_future(reader.read(1))  # returns at EOF: No or Esc
        cancelled = asyncio.ensure_future(pending.cancelled.wait())
        answer: contracts.Decision | None
        try:
            done, _ = await asyncio.wait(
                {decide, hook_gone, cancelled},
                timeout=self.max_wait_s,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if decide in done:
                answer, reason = decide.result(), "decided"
            elif cancelled in done:
                answer, reason = decision(pending, "handoff"), pending.cancel_reason or "cancelled"
            elif hook_gone in done:
                answer, reason = None, "hook_closed"
            else:
                answer, reason = decision(pending, "handoff"), "timeout"
        finally:
            for task in (decide, hook_gone, cancelled):
                task.cancel()
            self.pending.remove(request.id)

        if answer is not None:
            try:
                writer.write(wire.encode(answer.model_dump(mode="json", exclude_none=True)))
                await writer.drain()
            except OSError:
                answer = None  # the hook left as we answered
        outcome = answer.outcome if answer is not None else "cancelled"
        seconds = time.monotonic() - pending.received
        self.resolved.append(
            Resolved(request.id, request.session_id, request.tool_name, outcome, reason, seconds)
        )
        log.info("request %s: %s (%s) after %.1f s", request.id, outcome, reason, seconds)
        self._audit(pending, outcome, reason)

    def _audit(self, pending: Pending, outcome: str, reason: str) -> None:
        """One keyed, chained line per decision (D-025). Secrets are redacted first."""
        if self.audit_log is None:
            return
        request = pending.request
        notes = pending.notes
        if "tier" not in notes or "rules" not in notes:  # the decider didn't judge it
            judgement = engine.judge_request(self.where, request, pending.session.config_edited)
            notes.setdefault("tier", judgement.tier)
            notes.setdefault("rules", list(judgement.rules))
        try:
            self.audit_log.append(
                id=request.id,
                session=pending.session.name,
                tool=request.tool_name,
                input_sha256=pending.input_sha256,
                input_redacted=redact.redact(json.dumps(request.tool_input))[:2000],
                tier=notes["tier"],
                rules=notes["rules"],
                spoken=notes.get("spoken"),
                transcript=notes.get("transcript"),
                recognizer=notes.get("recognizer"),
                outcome=outcome,
                reason=reason,
                timings_ms=notes.get("timings_ms", {}),
            )
        except Exception:
            log.exception("couldn't write the audit log for %s", request.id)

    def _observe(self, request: contracts.ApprovalRequest, session: Session) -> None:
        """Observe mode (D-021): one line per prompt, with no command text or file contents."""
        judgement = engine.judge_request(self.where, request, session.config_edited)
        session_name = session.name
        record = {
            "ts": wire.utc_timestamp(),
            "session": session_name,
            "permission_mode": request.permission_mode,
            "tool": request.tool_name,
            "tier": judgement.tier,
            "voice_ok": judgement.tier in engine.VOICE_TIERS,
            "reason": "; ".join(judgement.rules),
        }
        line = (json.dumps(record) + "\n").encode()
        try:
            fd = os.open(self.where.observe_log, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            try:
                os.write(fd, line)
            finally:
                os.close(fd)
        except OSError:
            log.exception("couldn't write the observe log")

    async def _decide(self, pending: Pending) -> contracts.Decision:
        """The decider's answer, or a hand-off if it fails or answers the wrong request."""
        try:
            answer = await self.decider(pending)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("the decider failed on %s; handing off", pending.request.id)
            return decision(pending, "handoff")
        if answer.id != pending.request.id:
            log.error("the decider answered %s for %s; handing off", answer.id, pending.request.id)
            return decision(pending, "handoff")
        return answer


def run_forever(where: paths.Paths, observe: bool = False, decider: Decider = hand_off) -> None:
    """Run the daemon in this process until SIGTERM or SIGINT."""
    import signal

    async def main() -> None:
        daemon = Daemon(
            where,
            decider=decider,
            observe=observe,
            audit_log=audit.AuditLog(where.audit_dir, audit.load_key(where)),
        )
        loop = asyncio.get_running_loop()
        for signum in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(signum, daemon.stop)
        await daemon.serve()

    os.umask(0o077)  # anything the daemon writes is private
    asyncio.run(main())
