"""The `earshot` command: install and remove Earshot's hooks, and read the observe log.

earshot init [--settings FILE] [--home DIR]
earshot uninstall [--settings FILE]
earshot observe [--home DIR]
"""

from __future__ import annotations

import argparse
import collections
import json
import shlex
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from earshot import audit, auth, paths, service, wire
from earshot.connectors.claude_code import settings

DEFAULT_SETTINGS = Path.home() / ".claude" / "settings.json"


def hook_command(home: str | None) -> str:
    """The hook as Claude Code should run it: this environment's `earshot-hook`, by full path."""
    script = Path(sys.executable).parent / "earshot-hook"
    words = [str(script)]
    if home:
        words += ["--home", str(Path(home).expanduser().resolve())]
    return " ".join(shlex.quote(word) for word in words)


def init(args: argparse.Namespace) -> int:
    where = paths.resolve(args.home)
    auth.ensure_token(where.token)
    target = Path(args.settings).expanduser()
    settings.install(target, hook_command(args.home))
    print(f"Added Earshot's hooks to {target}.")
    backup = settings.backup_path(target)
    if backup.exists():
        print(f"The file as it was is saved in {backup}; earshot uninstall puts it back.")
    print(f"The token is in {where.token}. Start the daemon with: earshotd", end="")
    print(f" --home {shlex.quote(args.home)}" if args.home else "")
    return 0


def uninstall(args: argparse.Namespace) -> int:
    print(settings.uninstall(Path(args.settings).expanduser()))
    return 0


def summarise(records: list[dict[str, Any]]) -> list[str]:
    """The observe log in a few lines: how many prompts, how often, and of what kind."""
    if not records:
        return ["No prompts recorded yet."]
    times = sorted(datetime.fromisoformat(r["ts"].replace("Z", "+00:00")) for r in records)
    days = {t.date() for t in times}
    hours = (times[-1] - times[0]).total_seconds() / 3600
    count = f"{len(records)} prompt" + ("" if len(records) == 1 else "s")
    rate = (
        f"{len(records) / hours:.1f} an hour across that span, {len(records) / len(days):.1f} a day"
        if hours >= 1
        else "less than an hour of data, too little for a rate"
    )
    voice = sum(1 for r in records if r.get("voice_ok"))
    lines = [
        f"{count} from {times[0]:%d %b %H:%M} to {times[-1]:%d %b %H:%M} UTC, "
        f"on {len(days)} day(s): {rate}.",
        f"Voice could approve {voice} of them under the safety stub (D-019); "
        f"{len(records) - voice} would go to the screen.",
    ]
    for title, key in (("Permission mode", "permission_mode"), ("Tool", "tool"), ("Why", "reason")):
        counts = collections.Counter(str(r.get(key)) for r in records)
        lines.append(f"{title}: " + ", ".join(f"{k} {n}" for k, n in counts.most_common()))
    return lines


def observe(args: argparse.Namespace) -> int:
    log = paths.resolve(args.home).observe_log
    try:
        text = log.read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"No observe log at {log} yet. Run earshotd --observe and work as usual.")
        return 1
    records = []
    for line in text.splitlines():
        try:
            records.append(json.loads(line))
        except ValueError:
            continue
    print("\n".join(summarise(records)))
    return 0


def audit_verify(args: argparse.Namespace) -> int:
    where = paths.resolve(args.home)
    anchor = audit.anchor_store(where).load()
    problems = audit.verify(where.audit_dir, audit.load_key(where), anchor)
    if problems:
        print("The audit log has problems:\n" + "\n".join(f"  {p}" for p in problems))
        return 1
    anchored = f", and matches its anchor ({anchor.length} records)" if anchor else ""
    print(f"The audit log in {where.audit_dir} is intact{anchored}.")
    return 0


def audit_tail(args: argparse.Namespace) -> int:
    where = paths.resolve(args.home)
    log = audit.AuditLog(where.audit_dir, audit.load_key(where))
    for record in list(log.records())[-args.lines :]:
        said = f' said "{record.get("transcript")}"' if record.get("transcript") else ""
        print(
            f"{record.get('ts', '?')}  {record.get('session', '?')}: {record.get('tool', '?')} "
            f"-> {record.get('outcome', '?')} ({record.get('reason', '')}){said}"
        )
    return 0


def service_install(args: argparse.Namespace) -> int:
    where = paths.resolve(args.home)
    daemon_args = []
    if args.home:
        daemon_args += ["--home", str(Path(args.home).expanduser().resolve())]
    if args.voice:
        daemon_args.append("--voice")
    if args.helper:
        daemon_args += ["--helper", str(Path(args.helper).expanduser().resolve())]
    if args.stem:
        daemon_args.append("--stem")
    print(service.install(daemon_args, where.state_dir / "earshotd.log"))
    return 0


def service_uninstall(args: argparse.Namespace) -> int:
    print(service.uninstall())
    return 0


def _check(ok: bool, good: str, bad: str) -> bool:
    print(f"  {'ok ' if ok else 'NO '} {good if ok else bad}")
    return ok


def doctor(args: argparse.Namespace) -> int:
    """Check each piece Earshot needs, and say what to do about anything missing."""
    import importlib.util
    import socket
    import stat

    where = paths.resolve(args.home)
    target = Path(args.settings).expanduser()
    print("Earshot doctor")
    results = []
    text = target.read_text(encoding="utf-8") if target.exists() else ""
    results.append(
        _check(
            settings.MARKER in text,
            f"hooks are in {target}",
            f"no hooks in {target}: run earshot init",
        )
    )
    token_ok = where.token.exists() and stat.S_IMODE(where.token.stat().st_mode) == 0o600
    results.append(_check(token_ok, "the token is private", f"no private token at {where.token}"))
    reachable = False
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
            conn.settimeout(1)
            conn.connect(str(where.socket))
            reachable = True
    except OSError:
        pass
    results.append(
        _check(
            reachable,
            "earshotd is running",
            "earshotd isn't running: start it, or earshot service install",
        )
    )
    voice = importlib.util.find_spec("mlx_audio") is not None
    results.append(
        _check(
            voice, "the voice libraries are installed", "no voice libraries: uv sync --group voice"
        )
    )
    if voice:
        from earshot.voice.mac import MacVoice

        headset = MacVoice(headset=args.headset).headset_ready()
        results.append(
            _check(
                headset,
                f"the output is your {args.headset}",
                f"the output isn't your {args.headset}: connect it to the Mac",
            )
        )
        from earshot.voice import voiceprint

        profile = voiceprint.load(where.voiceprint)
        model = (where.models_dir / voiceprint.MODEL).exists()
        state = "calibrated" if profile and profile.calibrated else "not yet calibrated"
        results.append(
            _check(
                profile is not None and model,
                f"your voiceprint is enrolled ({state}): tier 2 can be asked by voice",
                "no voiceprint: tier 2 stays on the screen until you run earshot enroll"
                + ("" if model else " (first: uv run dev/export_ecapa.py)"),
            )
        )
    if sys.platform == "darwin":
        results.append(
            _check(
                service.loaded(),
                "the LaunchAgent is loaded",
                "no LaunchAgent: earshot service install (optional)",
            )
        )
    anchor = audit.anchor_store(where).load()
    problems = audit.verify(where.audit_dir, audit.load_key(where), anchor)
    intact = problems in ([], ["the log is empty"])
    results.append(_check(intact, "the audit log is intact", "; ".join(problems)))
    print("The microphone permission shows up the first time Earshot listens.")
    return 0 if all(results) else 1


def test_approval(args: argparse.Namespace) -> int:
    """One made-up request through the running daemon, the way Claude Code would send it."""
    import json
    import os
    import subprocess
    import tempfile

    # A plain folder name: Earshot says the project's name, and spells out a random one.
    scratch = tempfile.TemporaryDirectory(prefix="earshot-")
    folder = os.path.join(scratch.name, "earshot-test")  # noqa: PTH118
    os.mkdir(folder)  # noqa: PTH102
    payload = {
        "hook_event_name": "PermissionRequest",
        "session_id": f"earshot-test-{wire.new_request_id()}",  # new each time: a fresh name
        "prompt_id": wire.new_request_id(),
        "cwd": folder,
        "permission_mode": "default",
        "tool_name": "Write",
        "tool_input": {"file_path": os.path.join(folder, "notes.md"), "content": "hello"},  # noqa: PTH118
    }
    what = "write notes.md"
    if args.tier == 2:  # an install: a challenge word, and the voiceprint (milestones 5, 6)
        payload["tool_name"], payload["tool_input"] = "Bash", {"command": "pip install httpx"}
        what = "pip install httpx, at tier 2"
    print(f"Sending a test request: {what}. Answer by voice, or wait for the screen.")
    script = Path(sys.executable).parent / "earshot-hook"
    command = [str(script)] + (["--home", args.home] if args.home else [])
    with scratch:
        result = subprocess.run(  # noqa: S603 - our own hook, with fixed arguments
            command, input=json.dumps(payload).encode(), capture_output=True, check=False
        )
    if not result.stdout:
        print("Result: handed to the screen (or no daemon is running).")
        return 0
    decision = json.loads(result.stdout)["hookSpecificOutput"]["decision"]
    print(
        f"Result: {decision['behavior']}"
        + (f": {decision['message']}" if decision.get("message") else "")
    )
    return 0


def enroll(args: argparse.Namespace) -> int:
    """Record your voiceprint, or a friend's phrases for calibration (Phase 2, milestone 6)."""
    from earshot.voice import voiceprint

    if sys.platform != "darwin":
        print("earshot enroll needs the Mac's voice (macOS on Apple Silicon).", file=sys.stderr)
        return 1
    where = paths.resolve(args.home)
    model = where.models_dir / voiceprint.MODEL
    if not model.exists():
        home = f" --home {shlex.quote(args.home)}" if args.home else ""
        print(f"No voiceprint model at {model}. Make it with: uv run dev/export_ecapa.py{home}")
        return 1
    thread = None
    if args.helper:  # record through the helper, as earshotd --helper listens
        from earshot.daemon.server import AlreadyRunningError
        from earshot.voice import helper

        thread = helper.LinkThread(
            helper.HelperLink(where.helper_socket, auth.ensure_token(where.token))
        )
        try:
            thread.start()
        except AlreadyRunningError:
            print("earshotd is running with the helper. Stop it first, then run this again.")
            return 1
        problem = helper.launch(args.helper, where.helper_socket, where.token, args.headset)
        if problem or not thread.wait():
            print(f"The helper didn't connect{': ' + problem if problem else ''}. Is it built?")
            thread.stop()
            return 1
        if thread.link.permission.get("mic") != "granted":
            print("macOS is asking to let Earshot use the microphone, and motion: allow both.")
        if not thread.allowed():
            print("The helper isn't allowed the microphone (System Settings > Privacy & Security).")
            thread.stop()
            return 1
    try:
        return _enroll(args, where, model, thread.link if thread else None)
    finally:
        if thread is not None:
            thread.stop()


def _enroll(args: argparse.Namespace, where: paths.Paths, model: Path, link: Any) -> int:
    from earshot.voice import challenge, voiceprint
    from earshot.voice import enroll as enrolling
    from earshot.voice.mac import MacVoice

    voice = MacVoice(headset=args.headset, helper=link)
    if not voice.headset_ready():
        print(f"Connect your {args.headset} and make them the sound output first.")
        return 1
    print("Loading the voice models…")
    voice.load()
    embedder = voiceprint.Embedder(model)
    keep = Path(args.save_clips) if args.save_clips else None
    if args.record:
        keep = (keep or where.state_dir / "calibration") / args.record
        print(f"Recording {args.phrases} phrases from {args.record}, for calibration only.")
        words = challenge.words()[: args.phrases]
        enrolling.collect(voice.record_phrase, embedder.embed, list(words), print, keep)
        print(f"Saved to {keep}. No profile was made.")
        return 0
    print(f"After each prompt and its tone, say the phrase. {args.phrases + args.held_out} in all.")
    profile = enrolling.enroll(
        voice.record_phrase,
        embedder.embed,
        where.voiceprint,
        print,
        args.phrases,
        args.held_out,
        keep,
    )
    return 0 if profile else 1


def _command(args: argparse.Namespace, command: str, arg: str | None = None) -> int:
    from earshot.daemon import client

    reply = client.send(paths.resolve(args.home), command, arg)
    if reply is None:
        print("earshotd isn't running (or didn't answer).", file=sys.stderr)
        return 1
    print(reply.text)
    return 0 if reply.ok else 1


def mode(args: argparse.Namespace) -> int:
    """Set what Earshot announces: quiet, focus or chatty (Phase 4)."""
    return _command(args, "mode", args.name)


def status(args: argparse.Namespace) -> int:
    """What every session is doing, as Earshot would say it."""
    return _command(args, "status")


def talk(args: argparse.Namespace) -> int:
    """Push-to-talk from the keyboard: Earshot plays its tone and listens for one command."""
    return _command(args, "talk")


def policy_check(args: argparse.Namespace) -> int:
    """The tier a request would get, and why, without speaking (the spec's dry run)."""
    from earshot.policy import engine

    try:
        request = json.loads(Path(args.request).read_text(encoding="utf-8"))
        tool_name, tool_input = request["tool_name"], request["tool_input"]
        cwd = request.get("cwd") or str(Path.cwd())
        if not isinstance(tool_name, str) or not isinstance(tool_input, dict):
            raise TypeError("tool_name must be a string and tool_input an object")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"earshot: can't read a request from {args.request}: {exc}", file=sys.stderr)
        return 1
    judgement = engine.judge_at(paths.resolve(args.home), tool_name, tool_input, cwd)
    voice = "by voice" if judgement.tier in engine.VOICE_TIERS else "on the screen"
    print(f"Tier {judgement.tier}: {tool_name}, answered {voice} for now.")
    for why in judgement.rules:
        print(f"  {why}")
    if judgement.critical:
        print(f"Critical fields: {', '.join(judgement.critical)}")
    return 0


def policy_trust(args: argparse.Namespace) -> int:
    """Let a repo's policy lower tiers, until the file changes (P-11)."""
    from earshot.policy.file import PolicyError, trust

    target = Path(args.path)
    if not target.is_file():
        print(f"earshot: no policy file at {target}", file=sys.stderr)
        return 1
    try:
        pinned = trust(target, paths.resolve(args.home).trusted_policies)
    except PolicyError as exc:
        print(f"earshot: {exc}", file=sys.stderr)
        return 1
    print(f"Trusted {target.resolve()} (sha256 {pinned[:12]}…).")
    print("Its rules can now lower tiers. Any change to the file undoes this.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="earshot", description="Answer Claude Code by voice.")
    commands = parser.add_subparsers(dest="command", required=True)

    p = commands.add_parser("init", help="add Earshot's hooks to Claude Code's settings")
    p.add_argument("--settings", default=str(DEFAULT_SETTINGS), help="the settings file to edit")
    p.add_argument("--home", help="Earshot's folder for the token, socket and logs")
    p.set_defaults(run=init)

    p = commands.add_parser("uninstall", help="remove Earshot's hooks again")
    p.add_argument("--settings", default=str(DEFAULT_SETTINGS), help="the settings file to edit")
    p.set_defaults(run=uninstall)

    p = commands.add_parser("observe", help="summarise the prompts observe mode has logged")
    p.add_argument("--home", help="Earshot's folder for the token, socket and logs")
    p.set_defaults(run=observe)

    p = commands.add_parser("audit", help="check or read the audit log")
    audit_commands = p.add_subparsers(dest="audit_command", required=True)
    q = audit_commands.add_parser("verify", help="check the chain for edits and deletions")
    q.add_argument("--home", help="Earshot's folder for the token, socket and logs")
    q.set_defaults(run=audit_verify)
    q = audit_commands.add_parser("tail", help="show the latest decisions")
    q.add_argument("--home", help="Earshot's folder for the token, socket and logs")
    q.add_argument("-n", "--lines", type=int, default=10, help="how many (default 10)")
    q.set_defaults(run=audit_tail)

    p = commands.add_parser("service", help="start earshotd at login (macOS)")
    service_commands = p.add_subparsers(dest="service_command", required=True)
    q = service_commands.add_parser("install", help="install and load the LaunchAgent")
    q.add_argument("--home", help="Earshot's folder for the token, socket and logs")
    q.add_argument("--voice", action="store_true", help="run the daemon with --voice")
    q.add_argument("--helper", metavar="APP", help="run the daemon with --helper APP")
    q.add_argument("--stem", action="store_true", help="run the daemon with --stem")
    q.set_defaults(run=service_install)
    q = service_commands.add_parser("uninstall", help="stop and remove the LaunchAgent")
    q.set_defaults(run=service_uninstall)

    p = commands.add_parser("doctor", help="check everything Earshot needs")
    p.add_argument("--home", help="Earshot's folder for the token, socket and logs")
    p.add_argument("--settings", default=str(DEFAULT_SETTINGS), help="the settings file")
    p.add_argument("--headset", default="AirPods", help="part of the headset's device name")
    p.set_defaults(run=doctor)

    p = commands.add_parser("enroll", help="record your voiceprint through the AirPods (macOS)")
    p.add_argument("--home", help="Earshot's folder for the token, socket and logs")
    p.add_argument("--headset", default="AirPods", help="part of the headset's device name")
    p.add_argument("--phrases", type=int, default=12, help="phrases for the profile (default 12)")
    p.add_argument("--held-out", type=int, default=6, help="phrases to check it with (default 6)")
    p.add_argument("--save-clips", help="also keep the phrases as WAV files here, for calibration")
    p.add_argument(
        "--record", metavar="NAME", help="only record NAME's phrases, for calibration; no profile"
    )
    p.add_argument(
        "--helper",
        metavar="APP",
        help="record through the signed helper (EarshotMotion.app), as earshotd --helper listens",
    )
    p.set_defaults(run=enroll)

    p = commands.add_parser("policy", help="check requests against your policy, or trust a repo's")
    policy_commands = p.add_subparsers(dest="policy_command", required=True)
    q = policy_commands.add_parser("check", help="print the tier a saved request would get")
    q.add_argument("request", help="a JSON file with tool_name, tool_input and cwd")
    q.add_argument("--home", help="Earshot's folder for the token, socket and logs")
    q.set_defaults(run=policy_check)
    q = policy_commands.add_parser("trust", help="let a repo's policy lower tiers (pins its hash)")
    q.add_argument("path", nargs="?", default=".earshot/policy.yaml", help="the repo's policy file")
    q.add_argument("--home", help="Earshot's folder for the token, socket and logs")
    q.set_defaults(run=policy_trust)

    p = commands.add_parser("mode", help="set what Earshot announces: quiet, focus or chatty")
    p.add_argument("name", choices=["quiet", "focus", "chatty"])
    p.add_argument("--home", help="Earshot's folder for the token, socket and logs")
    p.set_defaults(run=mode)

    p = commands.add_parser("status", help="what every session is doing, as Earshot would say it")
    p.add_argument("--home", help="Earshot's folder for the token, socket and logs")
    p.set_defaults(run=status)

    p = commands.add_parser("talk", help="push-to-talk from the keyboard: say one command")
    p.add_argument("--home", help="Earshot's folder for the token, socket and logs")
    p.set_defaults(run=talk)

    p = commands.add_parser("test", help="send one made-up request through the running daemon")
    p.add_argument("--home", help="Earshot's folder for the token, socket and logs")
    p.add_argument(
        "--tier", type=int, choices=(1, 2), default=1, help="2 asks for a challenge word"
    )
    p.set_defaults(run=test_approval)

    args = parser.parse_args(argv)
    try:
        code: int = args.run(args)
    except settings.SettingsError as exc:
        print(f"earshot: {exc}", file=sys.stderr)
        return 1
    return code


if __name__ == "__main__":
    sys.exit(main())
