"""Adding Earwarden's hooks to a Claude Code settings file, and taking them out again.

`earwarden init` keeps a byte-for-byte backup of the file as it was. `earwarden uninstall`
removes only Earwarden's entries; if nothing else changed meanwhile, it puts the backup back
exactly.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

MARKER = "earwarden-hook"
HOOK_TIMEOUT_S = 300  # longer than the hook's own 290 s wait (D-020)
EVENT_TIMEOUT_S = 10
EVENTS = ("PostToolUse", "Notification", "Stop", "SessionStart", "SessionEnd")


class SettingsError(RuntimeError):
    pass


def backup_path(settings: Path) -> Path:
    return settings.with_name(settings.name + ".earwarden-backup")


def _is_ours(group: Any) -> bool:
    hooks = group.get("hooks") if isinstance(group, dict) else None
    return isinstance(hooks, list) and any(
        isinstance(h, dict) and MARKER in str(h.get("command", "")) for h in hooks
    )


def without_earwarden(settings: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = json.loads(json.dumps(settings))
    hooks = result.get("hooks")
    if not isinstance(hooks, dict):
        return result
    for event in list(hooks):
        groups = hooks[event]
        if isinstance(groups, list):
            kept = [g for g in groups if not _is_ours(g)]
            if kept:
                hooks[event] = kept
            else:
                del hooks[event]
    if not hooks:
        del result["hooks"]
    return result


def with_earwarden(settings: dict[str, Any], command: str) -> dict[str, Any]:
    result = without_earwarden(settings)
    hooks = result.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise SettingsError('"hooks" in the settings file isn\'t an object')
    hooks.setdefault("PermissionRequest", []).append(
        {
            "matcher": "*",
            "hooks": [{"type": "command", "command": command, "timeout": HOOK_TIMEOUT_S}],
        }
    )
    for event in EVENTS:
        group: dict[str, Any] = {
            "hooks": [
                {"type": "command", "command": f"{command} --event", "timeout": EVENT_TIMEOUT_S}
            ]
        }
        if event == "PostToolUse":
            group = {"matcher": "*", **group}
        hooks.setdefault(event, []).append(group)
    return result


def _read(path: Path) -> dict[str, Any]:
    try:
        data: Any = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise SettingsError(f"{path} isn't valid JSON, so it was left alone: {exc}") from exc
    if not isinstance(data, dict):
        raise SettingsError(f"{path} doesn't hold a JSON object, so it was left alone")
    checked: dict[str, Any] = data
    return checked


def _write(path: Path, data: dict[str, Any] | bytes) -> None:
    text = data if isinstance(data, bytes) else (json.dumps(data, indent=2) + "\n").encode()
    temporary = path.with_name(path.name + ".earwarden-new")
    temporary.write_bytes(text)
    if path.exists():
        os.chmod(temporary, path.stat().st_mode & 0o777)  # noqa: PTH101
    temporary.replace(path)


def install(path: Path, command: str) -> None:
    """Add Earwarden's hooks, backing up the file the first time."""
    current = _read(path) if path.exists() else {}
    backup = backup_path(path)
    if path.exists() and not backup.exists():
        backup.write_bytes(path.read_bytes())
    path.parent.mkdir(parents=True, exist_ok=True)
    _write(path, with_earwarden(current, command))


def uninstall(path: Path) -> str:
    """Remove Earwarden's hooks. Returns what was done, in a sentence."""
    backup = backup_path(path)
    if not path.exists():
        return f"{path} doesn't exist; nothing to remove."
    cleaned = without_earwarden(_read(path))
    if backup.exists():
        original = backup.read_bytes()
        if json.loads(original) == cleaned:
            _write(path, original)
            backup.unlink()
            return f"Restored {path} exactly as it was before earwarden init."
        _write(path, cleaned)
        return (
            f"Removed Earwarden's hooks from {path}. It changed since earwarden init, so the "
            f"backup stays at {backup}."
        )
    if cleaned:
        _write(path, cleaned)
    else:
        path.unlink()
        return f"Removed {path}, which held only Earwarden's hooks."
    return f"Removed Earwarden's hooks from {path}."
