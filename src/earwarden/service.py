"""Running earwardend at login with a launchd LaunchAgent (macOS), and restarting it if it crashes.

`earwarden service install` writes `~/Library/LaunchAgents/dev.earwarden.daemon.plist` and loads it;
`earwarden service uninstall` unloads and removes it. Started by launchd, the daemon's Python
gets its own microphone prompt the first time (Step 0's launchd check).
"""

from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from pathlib import Path

LABEL = "dev.earwarden.daemon"
LAUNCHCTL = "/bin/launchctl"
HF_VARIABLES = ("HF_HOME", "HF_HUB_CACHE")  # where the voice's models are kept


def plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def agent(daemon_args: list[str], log_file: Path) -> bytes:
    """The LaunchAgent: this environment's earwardend, started at login and kept alive."""
    program = str(Path(sys.executable).parent / "earwardend")
    fields: dict[str, object] = {
        "Label": LABEL,
        "ProgramArguments": [program, *daemon_args],
        "RunAtLoad": True,
        "KeepAlive": True,
        "ProcessType": "Interactive",  # audio wants low latency
        "StandardOutPath": str(log_file),
        "StandardErrorPath": str(log_file),
    }
    # launchd doesn't read your shell, so the models stay where dev/activate put them (D-013),
    # instead of downloading again into ~/.cache.
    cache = {name: os.environ[name] for name in HF_VARIABLES if os.environ.get(name)}
    if cache:
        fields["EnvironmentVariables"] = cache
    return plistlib.dumps(fields)


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
    return f"earwardend now starts at login and restarts if it stops. Its log: {log_file}"


def uninstall() -> str:
    if sys.platform != "darwin":
        return "The LaunchAgent is macOS only."
    if loaded():
        _launchctl("bootout", f"gui/{os.getuid()}/{LABEL}")
    path = plist_path()
    if path.exists():
        path.unlink()
        return f"Stopped earwardend and removed {path}."
    return "No LaunchAgent was installed."
