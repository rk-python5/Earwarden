"""The version, the changelog and the installed metadata must agree (decisions.md, D-006)."""

import re
import tomllib
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DISTRIBUTION = "earwarden"
# Semantic Versioning core, with an optional PEP 440 development suffix between releases.
VERSION_RE = re.compile(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(\.dev(0|[1-9]\d*))?")


def _pyproject_version() -> str:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    version = data["project"]["version"]
    assert isinstance(version, str)
    return version


def _changelog() -> str:
    return (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")


def test_version_is_semver_in_pep440_form() -> None:
    assert VERSION_RE.fullmatch(_pyproject_version())


def test_installed_metadata_matches_pyproject() -> None:
    assert metadata.version(DISTRIBUTION) == _pyproject_version()


def test_changelog_matches_version() -> None:
    version = _pyproject_version()
    changelog = _changelog()
    assert "## [Unreleased]" in changelog

    base, _, dev = version.partition(".dev")
    heading = re.compile(rf"^## \[{re.escape(base)}\] - \d{{4}}-\d{{2}}-\d{{2}}$", re.MULTILINE)
    if dev:
        assert not heading.search(changelog), f"{base} is already released; bump to the next .dev"
    else:
        assert heading.search(changelog), f"CHANGELOG.md has no dated heading for {base}"
