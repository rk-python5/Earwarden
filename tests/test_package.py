"""Importing the package must stay cheap, because the stdlib-only hook client lives inside it."""

import subprocess
import sys


def test_import_pulls_in_no_other_modules() -> None:
    code = (
        "import sys\n"
        "before = set(sys.modules)\n"
        "import earshot\n"
        "print('\\n'.join(sorted(set(sys.modules) - before)))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.split() == ["earshot"]
