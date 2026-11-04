"""dev/activate parses in every shell rehaan might use, and refuses to run outside the repo."""

import shutil
import subprocess
from pathlib import Path

import pytest

ACTIVATE = Path(__file__).resolve().parents[1] / "dev" / "activate"
SHELLS = [shell for shell in ("sh", "bash", "zsh") if shutil.which(shell)]


@pytest.mark.parametrize("shell", SHELLS)
def test_parses(shell: str) -> None:
    subprocess.run([shell, "-n", str(ACTIVATE)], check=True)


@pytest.mark.parametrize("shell", SHELLS)
def test_refuses_outside_the_repo(shell: str, tmp_path: Path) -> None:
    result = subprocess.run(
        [shell, "-c", f'. "{ACTIVATE}"; echo "status $?"'],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert "from inside the Earshot repo" in result.stderr
    assert "status 1" in result.stdout
    assert not (tmp_path / ".tools").exists()
