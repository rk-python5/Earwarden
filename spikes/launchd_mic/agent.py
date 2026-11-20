"""Run mic_check.py as a launchd agent, the way earwardend would start, and report what happens.

    python3 spikes/launchd_mic/agent.py setup [--python 3.11]   # venv with sounddevice and numpy
    python3 spikes/launchd_mic/agent.py run                     # start under launchd, show result
    python3 spikes/launchd_mic/agent.py terminal                # same check from Terminal
    python3 spikes/launchd_mic/agent.py clean                   # unload and remove the agent

Nothing is installed in ~/Library/LaunchAgents: launchctl loads the plist from out/ for one run
and unloads it afterwards. Standard library only. macOS only.
"""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
VENV = OUT / "venv"
PLIST = OUT / "dev.earwarden.spike.mic.plist"
LABEL = "dev.earwarden.spike.mic"
RESULT = OUT / "launchd-result.json"


def domain() -> str:
    return f"gui/{os.getuid()}"


def venv_python() -> Path:
    return VENV / "bin" / "python"


def cmd_setup(args: argparse.Namespace) -> int:
    uv = shutil.which("uv")
    if uv is None:
        print("uv isn't on PATH", file=sys.stderr)
        return 1
    shutil.rmtree(VENV, ignore_errors=True)
    subprocess.run([uv, "venv", "--python", args.python, str(VENV)], check=True)
    subprocess.run(
        [uv, "pip", "install", "--python", str(venv_python()), "sounddevice", "numpy"], check=True
    )
    resolved = venv_python().resolve()
    print(f"\nInterpreter for the agent: {venv_python()}\n  which is really {resolved}")
    print("macOS keys the microphone permission to that real binary.")
    return 0


def write_plist(device: str | None) -> None:
    arguments = [str(venv_python()), str(HERE / "mic_check.py"), "--out", str(RESULT)]
    if device:
        arguments += ["--device", device]
    plist = {
        "Label": LABEL,
        "ProgramArguments": arguments,
        "RunAtLoad": False,
        "StandardOutPath": str(OUT / "launchd.log"),
        "StandardErrorPath": str(OUT / "launchd.log"),
    }
    PLIST.write_bytes(plistlib.dumps(plist))


def bootout() -> None:
    subprocess.run(
        ["launchctl", "bootout", f"{domain()}/{LABEL}"], capture_output=True, check=False
    )


def cmd_run(args: argparse.Namespace) -> int:
    if not venv_python().exists():
        print("Run setup first.", file=sys.stderr)
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    RESULT.unlink(missing_ok=True)
    write_plist(args.device)
    bootout()
    subprocess.run(["launchctl", "bootstrap", domain(), str(PLIST)], check=True)
    subprocess.run(["launchctl", "kickstart", "-k", f"{domain()}/{LABEL}"], check=True)
    print("Started under launchd. If macOS asks for microphone access, note the name it shows.")
    deadline = time.monotonic() + args.wait
    while not RESULT.exists() and time.monotonic() < deadline:
        time.sleep(0.5)
    bootout()
    if not RESULT.exists():
        print(f"No result after {args.wait:g} s; see {OUT / 'launchd.log'}", file=sys.stderr)
        return 1
    result = json.loads(RESULT.read_text(encoding="utf-8"))
    print(json.dumps(result, indent=2))
    print(f"\nVerdict under launchd: {result.get('verdict')}")
    return 0


def cmd_terminal(args: argparse.Namespace) -> int:
    command = [
        str(venv_python()),
        str(HERE / "mic_check.py"),
        "--out",
        str(OUT / "terminal-result.json"),
    ]
    if args.device:
        command += ["--device", args.device]
    return subprocess.run(command, check=False).returncode


def cmd_clean(args: argparse.Namespace) -> int:
    bootout()
    PLIST.unlink(missing_ok=True)
    print("Agent unloaded and plist removed. The venv stays in out/ until you delete it.")
    return 0


def main() -> int:
    if sys.platform != "darwin":
        print("launchd is macOS only.", file=sys.stderr)
        return 1
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--device", help="part of the input device's name, e.g. AirPods")
    commands = parser.add_subparsers(dest="command", required=True)
    setup = commands.add_parser("setup")
    setup.add_argument("--python", default="3.11", help="interpreter version for the venv")
    setup.set_defaults(func=cmd_setup)
    run = commands.add_parser("run")
    run.add_argument("--wait", type=float, default=60.0, help="seconds to wait for a result")
    run.set_defaults(func=cmd_run)
    commands.add_parser("terminal").set_defaults(func=cmd_terminal)
    commands.add_parser("clean").set_defaults(func=cmd_clean)
    args = parser.parse_args()
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    sys.exit(main())
