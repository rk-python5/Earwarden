"""Refresh the popular-package lists the lookalike check uses (P-09). Run at release time.

    uv run python dev/refresh_package_lists.py

It downloads, at development time only (Earwarden never fetches them at run time):

- PyPI: the 15,000 most-downloaded packages, from https://hugovk.dev/top-pypi-packages/, which
  counts PyPI's public download statistics. Only the names are kept.
- npm: npm-high-impact's list of the most-depended-upon and most-downloaded packages (MIT).

Then run the tests: `tests/test_lookalike.py` checks recall and false flags still hold.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "src" / "earwarden" / "policy" / "data"
PYPI = "https://hugovk.dev/top-pypi-packages/top-pypi-packages.min.json"
NPM_PACKAGE = "https://registry.npmjs.org/npm-high-impact/latest"
NPM_TOP = "https://unpkg.com/npm-high-impact@{version}/lib/top.js"


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310 - fixed https URLs
        data: bytes = response.read()
    return data


def main() -> int:
    pypi = json.loads(fetch(PYPI))
    names = [row["project"] for row in pypi["rows"]]
    (DATA / "pypi-top.txt").write_text(
        "# The 15,000 most-downloaded PyPI packages, most downloaded first: names only.\n"
        f"# From https://hugovk.dev/top-pypi-packages/ (dump of {pypi['last_update'][:10]}), "
        "which counts\n"
        "# PyPI's public download statistics. The source has no licence; the names are facts.\n"
        "# Refresh at release time with: uv run python dev/refresh_package_lists.py\n"
        + "\n".join(names)
        + "\n",
        encoding="utf-8",
    )
    version = json.loads(fetch(NPM_PACKAGE))["version"]
    top = re.findall(r"'([^']*)'", fetch(NPM_TOP.format(version=version)).decode())
    (DATA / "npm-top.txt").write_text(
        f"# The {len(top):,} most-depended-upon and most-downloaded npm packages: names only.\n"
        f"# From npm-high-impact {version} (lib/top.js), MIT licence, (c) Titus Wormer.\n"
        "# Refresh at release time with: uv run python dev/refresh_package_lists.py\n"
        + "\n".join(top)
        + "\n",
        encoding="utf-8",
    )
    print(f"PyPI: {len(names):,} names. npm: {len(top):,} names, from npm-high-impact {version}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
