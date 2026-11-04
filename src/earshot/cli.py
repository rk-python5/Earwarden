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

from earshot import audit, auth, paths
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
    problems = audit.verify(where.audit_dir, audit.load_key(where))
    if problems:
        print("The audit log has problems:\n" + "\n".join(f"  {p}" for p in problems))
        return 1
    print(f"The audit log in {where.audit_dir} is intact.")
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

    args = parser.parse_args(argv)
    try:
        code: int = args.run(args)
    except settings.SettingsError as exc:
        print(f"earshot: {exc}", file=sys.stderr)
        return 1
    return code


if __name__ == "__main__":
    sys.exit(main())
