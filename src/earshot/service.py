"""Running earshotd at login with a launchd LaunchAgent (macOS), and restarting it if it crashes.

`earshot service install` writes `~/Library/LaunchAgents/dev.earshot.daemon.plist` and loads it;
`earshot service uninstall` unloads and removes it. Started by launchd, the daemon's Python gets its
own microphone prompt the first time (Step 0's launchd check).
"""

from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from pathlib import Path

LABEL = "dev.earshot.daemon"
LAUNCHCTL = "/bin/launchctl"


def plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def agent(daemon_args: list[str], log_file: Path) -> bytes:
    """The LaunchAgent: this environment's earshotd, started at login and kept alive."""
    program = str(Path(sys.executable).parent / "earshotd")
    return plistlib.dumps(
        {
            "Label": LABEL,
            "ProgramArguments": [program, *daemon_args],
            "RunAtLoad": True,
            "KeepAlive": True,
            "ProcessType": "Interactive",  # audio wants low latency
            "StandardOutPath": str(log_file),
            "StandardErrorPath": str(log_file),
        }
    )


def _launchctl(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - the system launchctl with fixed verbs
        [LAUNCHCTL, *args], capture_output=True, text=True, check=False
    )


def loaded() -> bool:
    return _launchctl("print", f"gui/{os.getuid()}/{LABEL}").returncode == 0


def install(daemon_args: list[str], log_file: Path) -> str:
    if sys.platform != "darwin":
        return "The LaunchAgent is macOS only."
    path = plist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if loaded():
        _launchctl("bootout", f"gui/{os.getuid()}/{LABEL}")
    path.write_bytes(agent(daemon_args, log_file))
    result = _launchctl("bootstrap", f"gui/{os.getuid()}", str(path))
    if result.returncode != 0:
        return f"Wrote {path}, but launchctl couldn't load it: {result.stderr.strip()}"
    return f"earshotd now starts at login and restarts if it stops. Its log: {log_file}"


def uninstall() -> str:
    if sys.platform != "darwin":
        return "The LaunchAgent is macOS only."
    if loaded():
        _launchctl("bootout", f"gui/{os.getuid()}/{LABEL}")
    path = plist_path()
    if path.exists():
        path.unlink()
        return f"Stopped earshotd and removed {path}."
    return "No LaunchAgent was installed."
