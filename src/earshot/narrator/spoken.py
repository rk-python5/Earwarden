"""Spoken forms: code turned into words a voice can say and an ear can catch.

feature/login-v2               "feature slash login v2"
src/api/routes.py              "routes dot p y, in the api folder"
requests==2.32.3               "requests, version 2.32.3"
https://api.example.com/up     "example dot com"
"""

from __future__ import annotations

import posixpath
import re
from collections.abc import Callable
from urllib.parse import urlsplit


def spell(word: str) -> str:
    """Letter by letter, the way a word nobody can pronounce has to be said."""
    return " ".join(c.upper() if c.isalpha() else c for c in word if c.isalnum())


def identifier(text: str) -> str:
    """A branch or name: slashes said, dashes and underscores as spaces."""
    text = text.replace("/", " slash ")
    text = re.sub(r"[-_]+", " ", text)
    return " ".join(text.split())


def file_name(name: str) -> str:
    """routes.py becomes "routes dot p y": short extensions spelled out."""
    stem, dot, extension = name.rpartition(".")
    if not dot or not stem:
        return identifier(name)
    said = spell(extension).lower() if len(extension) <= 3 else identifier(extension)
    return f"{identifier(stem)} dot {said}"


def path(file_path: str, cwd: str | None = None) -> str:
    """A file and its folder, relative to the project when it's inside it."""
    absolute = posixpath.normpath(posixpath.join(cwd or "/", file_path))
    if cwd:
        root = posixpath.normpath(cwd)
        if absolute.startswith(root.rstrip("/") + "/"):
            parent = posixpath.dirname(absolute[len(root.rstrip("/")) + 1 :])
            where = f", in the {identifier(posixpath.basename(parent))} folder" if parent else ""
            return file_name(posixpath.basename(absolute)) + where
    parent = posixpath.basename(posixpath.dirname(absolute))
    where = f", in the {identifier(parent)} folder" if parent else ""
    return file_name(posixpath.basename(absolute)) + where + ", outside the project"


def package(spec: str) -> str:
    """requests==2.32.3 becomes "requests, version 2.32.3"."""
    match = re.match(r"^([A-Za-z0-9_.\[\]-]+)\s*(==|>=|<=|~=|@)?\s*(.*)$", spec)
    if not match:
        return identifier(spec)
    name, operator, version = match.groups()
    said = identifier(re.sub(r"\[.*\]", "", name))
    if operator and version:
        said += f", version {version}" if operator in ("==", "@") else f", version {version} or so"
    return said


def domain(url: str) -> str:
    """The registered domain only, with its dots said."""
    host = urlsplit(url if "://" in url else f"https://{url}").hostname or url
    labels = host.split(".")
    registered = ".".join(labels[-2:]) if len(labels) >= 2 else host
    return registered.replace(".", " dot ")


def speakable(text: str, can_say: Callable[[str], bool]) -> str:
    """Spell out every word the voice can't pronounce (D-024, from P-03).

    `can_say` asks the voice's own front-end (D-022) whether a word gets phonemes.
    """

    def fix(match: re.Match[str]) -> str:
        word = match.group()
        return word if word.isdigit() or can_say(word) else spell(word)

    return re.sub(r"[A-Za-z][A-Za-z0-9']*", fix, text)
