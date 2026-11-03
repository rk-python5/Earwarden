"""The launchd spike writes a valid agent plist that runs mic_check.py with the spike's venv."""

import plistlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "spikes" / "launchd_mic"))

import agent


def test_plist_runs_mic_check_with_the_venv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(agent, "OUT", tmp_path)
    monkeypatch.setattr(agent, "VENV", tmp_path / "venv")
    monkeypatch.setattr(agent, "PLIST", tmp_path / "agent.plist")
    monkeypatch.setattr(agent, "RESULT", tmp_path / "result.json")

    agent.write_plist("AirPods")

    plist = plistlib.loads((tmp_path / "agent.plist").read_bytes())
    assert plist["Label"] == agent.LABEL
    assert plist["RunAtLoad"] is False
    assert plist["ProgramArguments"] == [
        str(tmp_path / "venv" / "bin" / "python"),
        str(agent.HERE / "mic_check.py"),
        "--out",
        str(tmp_path / "result.json"),
        "--device",
        "AirPods",
    ]
    assert plist["StandardOutPath"] == str(tmp_path / "launchd.log")
