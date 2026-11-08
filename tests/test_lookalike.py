"""Lookalike packages (Phase 2, milestone 4): thresholds, confusables, recall, false flags."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from earshot.narrator.templates import narrate
from earshot.policy import engine, lookalike

CWD = "/Users/rehaan/code/api"
FIXTURE = Path(__file__).parent / "fixtures" / "typosquats.csv"


def like(name: str, registry: str = "pypi") -> str | None:
    hit = lookalike.check(name, registry)
    return hit.like if hit else None


@pytest.mark.parametrize(
    ("name", "target"),
    [
        ("reqeusts", "requests"),  # a swap counts as one edit
        ("requestss", "requests"),
        ("beautifulsoup5", "beautifulsoup4"),
        ("djangorestframwork", "djangorestframework"),
        ("djang0", "django"),  # a confusable, at any length
        ("nurnpy", "numpy"),  # rn for m
        ("Python_Dateutil", None),  # PEP 503: the same as python-dateutil
        ("requests", None),
        ("boto3", None),
        ("numoy", None),  # 5 letters: no edit-distance flag (P-09)
    ],
)
def test_pypi(name: str, target: str | None) -> None:
    assert like(name) == target


def test_letters_outside_ascii_are_flagged() -> None:
    assert like("r" + chr(0x435) + "quests") is not None  # a Cyrillic e


def test_npm_names_keep_their_separators() -> None:
    assert like("uglify.js", "npm") == "uglify-js"
    assert like("uglify-js", "npm") is None
    assert like("@types/node", "npm") is None


def test_every_listed_name_is_exempt() -> None:
    for registry in ("pypi", "npm"):
        names = [n for n in lookalike.LISTS[registry].read_text().splitlines() if n[:1] != "#"]
        assert all(lookalike.check(n, registry) is None for n in names[5000:5200])


def test_an_install_of_a_lookalike_is_tier_3_and_spelled_out(tmp_path: Path) -> None:
    command = "pip install reqeusts numpy"
    judgement = engine.judge("Bash", {"command": command}, CWD)
    assert judgement.tier == 3
    assert "minimum: reqeusts looks like requests (P-09)" in judgement.rules
    said = narrate("api", CWD, "Bash", {"command": command}, judgement)
    assert said.text == "api wants to install R E Q E U S T S, which looks like requests, numpy."
    (tmp_path / "requirements.txt").write_text("numpy\ndjangorestframwork==3.15\n")
    assert (
        engine.judge("Bash", {"command": "pip install -r requirements.txt"}, str(tmp_path)).tier
        == 3
    )


def test_registries_without_a_list_arent_checked() -> None:
    assert engine.judge("Bash", {"command": "brew install reqeusts"}, CWD).tier == 2


def squats(registry: str) -> list[dict[str, str]]:
    with FIXTURE.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(line for line in f if not line.startswith("#")))
    top = {n for bucket in lookalike.registry(registry).targets.values() for _, n in bucket}
    return [
        r
        for r in rows
        if r["ecosystem"] == registry
        and lookalike.normalize(r["target_package"], registry) in top
        and len(r["malicious_package"]) > 5
    ]


@pytest.mark.parametrize(("registry", "floor"), [("pypi", 0.85), ("npm", 0.65)])
def test_recall_on_known_squats(registry: str, floor: float) -> None:
    """Squats of popular names longer than 5 letters, from ecosyste.ms (8 Nov: 57/64 and 17/25)."""
    rows = squats(registry)
    caught = sum(lookalike.check(r["malicious_package"], registry) is not None for r in rows)
    assert caught / len(rows) >= floor


def test_false_flags_stay_near_four_percent() -> None:
    """P-09's measure: legitimate names ranked 5,001 on, as if they weren't on the list."""
    found = lookalike.registry("pypi")
    names = [n for n in lookalike.LISTS["pypi"].read_text().splitlines() if n[:1] != "#"]
    sample = [lookalike.normalize(n) for n in names[5000:5500]]
    without = found._replace(known=frozenset())
    flagged = 0
    for name in sample:
        flagged += _check_against(without, name)
    assert flagged / len(sample) < 0.08


def _check_against(found: lookalike.Registry, name: str) -> bool:
    if found.skeletons.get(lookalike.skeleton(name), name) != name:
        return True
    limit = lookalike.allowed_distance(name)
    return (
        any(
            target != name and lookalike.distance(name, target, limit) <= limit
            for length in range(len(name) - limit, len(name) + limit + 1)
            for _, target in found.targets.get(length, [])
        )
        if limit
        else False
    )
