"""Policy files: yours (`~/.earshot/policy.yaml`) and a repo's (`.earshot/policy.yaml`).

The format is the spec's, at version 1:

    version: 1
    defaults: { unknown_tool: 2 }
    rules:
      - id: tests
        match: { tool: Bash, command: '^pytest(\\s|$)' }
        tier: 1
    never_by_voice: [deploy]

`command` and `any_path` are regular expressions, searched (not anchored) in the Bash command and
in every path the request names. Unknown keys are errors, so a typo can't silently weaken a rule.

A repo's file can only raise tiers (P-11, D-029) until you trust it with `earshot policy trust`,
which pins its SHA-256. Any later change to the file makes it untrusted again.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Annotated

import yaml
from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError, field_validator

Tier = Annotated[StrictInt, Field(ge=0, le=3)]
REPO_POLICY = Path(".earshot") / "policy.yaml"


class PolicyError(Exception):
    """A policy file that can't be read or doesn't validate. Earshot then hands everything off."""


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class Match(Strict):
    tool: str | None = None
    command: str | None = None
    any_path: str | None = None

    @field_validator("command", "any_path")
    @classmethod
    def _compiles(cls, pattern: str | None) -> str | None:
        if pattern is not None:
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ValueError(f"not a valid regular expression: {exc}") from exc
        return pattern


class Rule(Strict):
    id: Annotated[str, Field(min_length=1, max_length=80)]
    match: Match
    tier: Tier
    critical: tuple[str, ...] = ()
    resolve: str | None = None


class Defaults(Strict):
    unknown_tool: Tier = 2


class PolicyFile(Strict):
    version: Annotated[StrictInt, Field(ge=1, le=1)]
    defaults: Defaults = Defaults()
    rules: tuple[Rule, ...] = ()
    never_by_voice: tuple[str, ...] = ()


def load(path: Path) -> PolicyFile | None:
    """The policy at `path`, None if there's no file, or PolicyError if it's broken."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise PolicyError(f"{path}: {exc.strerror}") from exc
    try:
        data = yaml.safe_load(text)
        # JSON round trip: YAML's dates and the like become plain values Pydantic can check.
        return PolicyFile.model_validate_json(json.dumps(data))
    except (yaml.YAMLError, TypeError, ValueError, ValidationError) as exc:
        raise PolicyError(f"{path}: {exc}") from exc


def find_repo_policy(cwd: str) -> Path | None:
    """The nearest `.earshot/policy.yaml` from the session's folder up to its git root."""
    folder = Path(cwd)
    for candidate in (folder, *folder.parents):
        if (candidate / REPO_POLICY).is_file():
            return candidate / REPO_POLICY
        if (candidate / ".git").exists():
            return None
    return None


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def trusted(path: Path, store: Path) -> bool:
    """Whether `path` is trusted, with the same contents as when it was trusted."""
    try:
        pins = json.loads(store.read_text(encoding="utf-8"))
        return isinstance(pins, dict) and pins.get(str(path.resolve())) == digest(path)
    except (OSError, ValueError):
        return False


def trust(path: Path, store: Path) -> str:
    """Pin `path`'s current contents as trusted, and return the hash."""
    load(path)  # a broken file isn't trusted
    try:
        pins = json.loads(store.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pins = {}
    if not isinstance(pins, dict):
        pins = {}
    pinned = digest(path)
    pins[str(path.resolve())] = pinned
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(json.dumps(pins, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return pinned
