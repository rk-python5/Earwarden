"""Where Earshot keeps its token, config, socket and audit log. Standard library only.

Real installs follow the plan: the token and config in `~/.earshot/`, the socket and the audit log
in `~/Library/Application Support/Earshot/`. Setting `EARSHOT_HOME`, or passing the hook's
`--home`, puts all of them in one folder instead. Development keeps that folder inside the repo,
under `.tools/earshot/` (D-013).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import NamedTuple

HOME_ENV = "EARSHOT_HOME"


class Paths(NamedTuple):
    config_dir: Path
    state_dir: Path

    @property
    def token(self) -> Path:
        return self.config_dir / "token"

    @property
    def config(self) -> Path:
        return self.config_dir / "config.toml"

    @property
    def socket(self) -> Path:
        return self.state_dir / "earshotd.sock"

    @property
    def audit_dir(self) -> Path:
        return self.state_dir / "audit"


def resolve(home: str | None = None) -> Paths:
    """The folders to use: `home` if given, else `EARSHOT_HOME`, else the plan's defaults."""
    chosen = home or os.environ.get(HOME_ENV)
    if chosen:
        root = Path(chosen).expanduser()
        return Paths(config_dir=root, state_dir=root)
    user = Path.home()
    if sys.platform == "darwin":
        state = user / "Library" / "Application Support" / "Earshot"
    else:  # Earshot runs on macOS; this keeps tests and tools working elsewhere
        state = user / ".earshot" / "state"
    return Paths(config_dir=user / ".earshot", state_dir=state)
