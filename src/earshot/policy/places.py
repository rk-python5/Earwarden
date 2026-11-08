"""Paths that decide a tier: the project's edge, protected places, build config and secrets.

Edit tools and Bash writes are judged the same way (P-01, P-02):

- secrets anywhere (`.env`, SSH keys, `*.pem`, `*.key`, credentials, `.netrc`, `.npmrc`,
  `.pypirc`, kube and docker config) are tier 3
- writing to `.git/`, `.github/workflows/` or `.envrc` is tier 3, and to the agent's or Earshot's
  own settings (`.claude/`, `.earshot/`, `.claude.json`) too: it would change their permissions
- writing to build and test config is at least tier 2, since that code runs later
- writing outside the project, or where a path can't be read in advance, is at least tier 2
"""

from __future__ import annotations

import posixpath
import re
from pathlib import Path, PurePosixPath

from earshot.policy.shell import UNSEEN

_START = r"(?:^|[\s/'\"=:`(])"
_END = r"(?=$|[\s'\"`;|&)<>])"
SECRET_PATHS = re.compile(  # the spec's rule, widened by P-02
    rf"{_START}\.env|id_(?:rsa|dsa|ecdsa|ed25519)|\.(?:pem|key){_END}|credentials|"
    rf"{_START}\.(?:netrc|npmrc|pypirc){_END}|\.kube/config|\.docker/config\.json"
)
PROTECTED_DIRS = (".git", ".github/workflows")
AGENT_DIRS = (".claude", ".earshot")
PROTECTED_FILES = {".envrc"}
AGENT_FILES = {".claude.json"}
CONFIG_FILES = {"conftest.py", "package.json", "Makefile", "pyproject.toml", "setup.py"}
DEVICES = re.compile(r"^/dev/(?:null|stdout|stderr|tty|fd/[0-9]+)$")

Limit = tuple[int, str]


def absolute(path: str, cwd: str) -> str:
    """`path` made absolute against `cwd`, with `~` expanded."""
    if path.startswith("~"):
        path = str(Path(path).expanduser())
    return posixpath.normpath(posixpath.join(cwd, path))


def inside(path: str, project: str, folder_too: bool = False) -> bool:
    """Whether an absolute `path` is inside the project; the folder itself counts for reads."""
    root = posixpath.normpath(project)
    return path.startswith(root.rstrip("/") + "/") or (folder_too and path == root)


def secret(text: str) -> bool:
    return SECRET_PATHS.search(text) is not None


def agent_files(path: str) -> str | None:
    """Which of the agent's or Earshot's own places `path` is in, if any."""
    parts = PurePosixPath(path).parts
    for name in AGENT_DIRS:
        if name in parts:
            return f"{name}/"
    return parts[-1] if parts and parts[-1] in AGENT_FILES else None


def _in_dir(parts: tuple[str, ...], directory: str) -> bool:
    depth = directory.count("/") + 1
    return any("/".join(parts[i : i + depth]) == directory for i in range(len(parts)))


def write_limits(path: str, cwd: str, project: str) -> list[Limit]:
    """Minimums and floor effects for writing `path` (relative to `cwd`) in `project`."""
    if UNSEEN in path:
        return [(2, "minimum: writes where the path can't be read in advance")]
    full = absolute(path, cwd)
    if DEVICES.match(full):
        return []
    limits: list[Limit] = []
    if secret(path) or secret(full):
        limits.append((3, "floor: secrets"))
    if (agent := agent_files(full)) is not None:
        limits.append((3, f"floor: change_agent_permissions ({agent})"))
    parts = PurePosixPath(full).parts
    for directory in PROTECTED_DIRS:
        if _in_dir(parts, directory):
            limits.append((3, f"floor: protected path ({directory}/)"))
    if parts and parts[-1] in PROTECTED_FILES:
        limits.append((3, f"floor: protected path ({parts[-1]})"))
    if parts and parts[-1] in CONFIG_FILES:
        limits.append((2, f"minimum: build or test config ({parts[-1]})"))
    if not inside(full, project):
        limits.append((2, "minimum: outside the project"))
    return limits
