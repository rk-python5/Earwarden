"""earwarden init and uninstall edit Claude Code's settings without disturbing anything else."""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from earwarden.cli import hook_command, main
from earwarden.connectors.claude_code import settings

COMMAND = "/repo/.venv/bin/earwarden-hook --home /repo/.tools/earwarden"

THEIRS = (
    '{\n    "model": "opus",\n    "hooks": {\n        "PermissionRequest": [\n'
    '            {"matcher": "Bash", "hooks": [{"type": "command", "command": "notify-me"}]}\n'
    "        ]\n    }\n}\n"
)


def test_init_adds_every_hook_earwarden_needs(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    settings.install(path, COMMAND)
    hooks = json.loads(path.read_text())["hooks"]
    assert set(hooks) == {"PermissionRequest", *settings.EVENTS}
    [permission] = hooks["PermissionRequest"]
    assert permission["hooks"] == [
        {"type": "command", "command": COMMAND, "timeout": settings.HOOK_TIMEOUT_S}
    ]
    for event in settings.EVENTS:
        [group] = hooks[event]
        assert group["hooks"][0]["command"] == f"{COMMAND} --event"
    assert hooks["PostToolUse"][0]["matcher"] == "*"


def test_init_keeps_your_own_settings_and_hooks(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(THEIRS)
    settings.install(path, COMMAND)
    data = json.loads(path.read_text())
    assert data["model"] == "opus"
    commands = [g["hooks"][0]["command"] for g in data["hooks"]["PermissionRequest"]]
    assert commands == ["notify-me", COMMAND]


def test_init_twice_adds_the_hooks_once(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(THEIRS)
    settings.install(path, COMMAND)
    settings.install(path, COMMAND)
    assert len(json.loads(path.read_text())["hooks"]["PermissionRequest"]) == 2
    assert settings.backup_path(path).read_text() == THEIRS  # the first backup is kept


def test_uninstall_restores_the_file_byte_for_byte(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(THEIRS)
    path.chmod(0o640)
    settings.install(path, COMMAND)
    assert stat.S_IMODE(path.stat().st_mode) == 0o640
    settings.uninstall(path)
    assert path.read_text() == THEIRS
    assert not settings.backup_path(path).exists()


def test_uninstall_keeps_changes_made_since_init(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(THEIRS)
    settings.install(path, COMMAND)
    data = json.loads(path.read_text())
    data["theme"] = "dark"
    path.write_text(json.dumps(data))
    message = settings.uninstall(path)
    left = json.loads(path.read_text())
    assert left["theme"] == "dark"
    assert "earwarden-hook" not in path.read_text()
    assert settings.backup_path(path).exists()
    assert "backup stays" in message


def test_a_file_that_held_only_earwarden_is_removed(tmp_path: Path) -> None:
    path = tmp_path / ".claude" / "settings.local.json"
    settings.install(path, COMMAND)
    settings.uninstall(path)
    assert not path.exists()


def test_a_broken_settings_file_is_left_alone(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("{ not json")
    with pytest.raises(settings.SettingsError):
        settings.install(path, COMMAND)
    assert path.read_text() == "{ not json"
    assert not settings.backup_path(path).exists()


def test_the_cli_installs_and_uninstalls(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "settings.json"
    path.write_text(THEIRS)
    home = tmp_path / "earwarden home"
    assert main(["init", "--settings", str(path), "--home", str(home)]) == 0
    assert (home / "token").exists()
    command = json.loads(path.read_text())["hooks"]["PermissionRequest"][1]["hooks"][0]["command"]
    assert command == hook_command(str(home))
    assert "'" in command  # the space in the folder name is quoted for the shell
    assert main(["uninstall", "--settings", str(path)]) == 0
    assert path.read_text() == THEIRS
    assert "Restored" in capsys.readouterr().out


def test_the_cli_reports_a_broken_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "settings.json"
    path.write_text("[]")
    assert main(["init", "--settings", str(path), "--home", str(tmp_path)]) == 1
    assert "left alone" in capsys.readouterr().err
