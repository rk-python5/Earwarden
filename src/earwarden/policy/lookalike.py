"""Lookalike packages: a name one slip away from a popular one is tier 3 (P-09, D-029).

Each package an install names is compared with its registry's most popular names, vendored in
`policy/data/` (nothing is fetched at run time):

- PyPI names are compared after PEP 503 normalisation (case, and runs of `-`, `_` and `.`, don't
  count). npm names only ignore case: there, `uglify.js` and `uglify-js` are different packages.
- Every name on the list is exempt, exact matches included.
- Edit distance (a swap of two letters counts as one edit) against the top 5,000 scales with the
  name's length: no flag up to 5 letters, 1 edit for 6 to 8, 2 for 9 or more. That keeps false
  flags near 4% of legitimate names, where a flat 2 would flag one in six (P-09).
- Confusable characters count at any length: a name that differs from a popular one only by
  `rn` for `m`, `vv` for `w`, `0` for `o`, or `1` or `i` for `l`, and names with letters outside
  ASCII.

A flagged name is spelled out and said to look like the popular one, and it goes to the screen.
"""

from __future__ import annotations

import re
from functools import cache
from pathlib import Path
from typing import NamedTuple

DATA = Path(__file__).parent / "data"
LISTS = {"pypi": DATA / "pypi-top.txt", "npm": DATA / "npm-top.txt"}
TARGETS = 5000  # the names squatters imitate; the rest of the list is only exempt
CONFUSABLE = [("rn", "m"), ("vv", "w"), ("0", "o"), ("1", "l"), ("i", "l")]
MANAGERS = {
    "pip": "pypi",
    "uv": "pypi",
    "pipx": "pypi",
    "poetry": "pypi",
    "npm": "npm",
    "pnpm": "npm",
    "yarn": "npm",
}


class Registry(NamedTuple):
    known: frozenset[str]  # every name on the list, normalised
    targets: dict[int, list[tuple[int, str]]]  # the top names by length: (rank, name)
    skeletons: dict[str, str]  # a top name's confusable skeleton, and the name


class Lookalike(NamedTuple):
    name: str  # as asked for
    like: str  # the popular name it looks like, or a description


def normalize(name: str, registry_name: str = "pypi") -> str:
    return name.lower() if registry_name == "npm" else re.sub(r"[-_.]+", "-", name).lower()


def skeleton(name: str) -> str:
    for confusable, plain in CONFUSABLE:
        name = name.replace(confusable, plain)
    return name


def requirement_name(spec: str, registry: str) -> str:
    """The package in a requirement: `requests[socks]>=2` is requests, `@a/b@^1` is @a/b."""
    if registry == "npm":
        scoped = spec.startswith("@")
        name = spec[1:].split("@", 1)[0] if scoped else spec.split("@", 1)[0]
        return ("@" if scoped else "") + name
    match = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", spec)
    return match.group(1) if match else spec


@cache
def registry(name: str) -> Registry:
    lines = LISTS[name].read_text(encoding="utf-8").splitlines()
    ranked = [normalize(line, name) for line in lines if line and not line.startswith("#")]
    targets: dict[int, list[tuple[int, str]]] = {}
    skeletons: dict[str, str] = {}
    for rank, known in enumerate(ranked[:TARGETS]):
        targets.setdefault(len(known), []).append((rank, known))
        skeletons.setdefault(skeleton(known), known)
    return Registry(frozenset(ranked), targets, skeletons)


def distance(a: str, b: str, limit: int) -> int:
    """Edit distance with swaps (optimal string alignment), or limit + 1 once it's over."""
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    before: list[int] = []
    row = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        current = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cost = a[i - 1] != b[j - 1]
            current[j] = min(row[j] + 1, current[j - 1] + 1, row[j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                current[j] = min(current[j], before[j - 2] + 1)
        if min(current) > limit:
            return limit + 1
        before, row = row, current
    return row[-1]


def allowed_distance(name: str) -> int:
    return 0 if len(name) <= 5 else 1 if len(name) <= 8 else 2


@cache
def check(name: str, registry_name: str) -> Lookalike | None:
    """Whether `name` looks like a popular package on `registry_name` without being one."""
    if registry_name not in LISTS:
        return None
    wanted = normalize(name, registry_name)
    found = registry(registry_name)
    if not wanted or wanted in found.known:
        return None
    if not wanted.isascii():
        return Lookalike(name, "a popular package, with unusual letters")
    if (like := found.skeletons.get(skeleton(wanted))) is not None:
        return Lookalike(name, like)
    limit = allowed_distance(wanted)
    best: tuple[int, str] | None = None
    for length in range(len(wanted) - limit, len(wanted) + limit + 1) if limit else ():
        for rank, target in found.targets.get(length, []):
            if (best is None or rank < best[0]) and distance(wanted, target, limit) <= limit:
                best = (rank, target)
    return Lookalike(name, best[1]) if best else None
