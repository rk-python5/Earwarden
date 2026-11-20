"""Where Earwarden keeps its token, config, socket and audit log. Standard library only.

Real installs follow the plan: the token and config in `~/.earwarden/`, the socket and the audit log
in `~/Library/Application Support/Earwarden/`. Setting `EARWARDEN_HOME`, or passing the hook's
`--home`, puts all of them in one folder instead. Development keeps that folder inside the repo,
under `.tools/earwarden/` (D-013).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import NamedTuple

HOME_ENV = "EARWARDEN_HOME"


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
        return self.state_dir / "earwardend.sock"

    @property
    def audit_dir(self) -> Path:
        return self.state_dir / "audit"

    @property
    def observe_log(self) -> Path:
        return self.state_dir / "observe.jsonl"

    @property
    def policy(self) -> Path:
        return self.config_dir / "policy.yaml"  # yours; a repo's is .earwarden/policy.yaml

    @property
    def trusted_policies(self) -> Path:
        return self.config_dir / "trusted-policies.json"  # repo policies pinned by hash (P-11)

    @property
    def helper_socket(self) -> Path:
        return self.state_dir / "helper.sock"  # where earwarden-motion connects (milestone 7)

    @property
    def voiceprint(self) -> Path:
        return self.config_dir / "voiceprint.json"  # your enrolled profile, readable only by you

    @property
    def models_dir(self) -> Path:
        return self.state_dir / "models"  # the voiceprint's ONNX model (dev/export_ecapa.py)

    @property
    def audio_dir(self) -> Path:
        return self.state_dir / "audio"  # only with earwardend --keep-audio


def resolve(home: str | None = None) -> Paths:
    """The folders to use: `home` if given, else `EARWARDEN_HOME`, else the plan's defaults."""
    chosen = home or os.environ.get(HOME_ENV)
    if chosen:
        root = Path(chosen).expanduser()
        return Paths(config_dir=root, state_dir=root)
    user = Path.home()
    if sys.platform == "darwin":
        state = user / "Library" / "Application Support" / "Earwarden"
    else:  # Earwarden runs on macOS; this keeps tests and tools working elsewhere
        state = user / ".earwarden" / "state"
    return Paths(config_dir=user / ".earwarden", state_dir=state)
