"""The fidelity checker: a summary may drop nothing and invent nothing (Phase 2, milestone 3).

Every sentence is checked before it's spoken, the template's now and a model's from Phase 3:

- Every critical field (`policy.fields`) must appear in it, in its spoken form.
- Every word must come from those fields, the session's name, or the narrator's own small
  vocabulary. A branch, path or package nobody asked for fails it.

A sentence that fails isn't spoken. A model's falls back to the template, and a template's sends the
request to the screen, so the checker can only make speech plainer, never less accurate.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import NamedTuple

from earshot.policy.fields import Action

_WORDS = """a and as at branch current data delete dot edit every fetch files folder force from
has in index install its long network on or outside packages project push read recursively request
run search secret send slash so something tests the then to upstream use value version waiting
wants web which looks like popular package unusual letters write"""
VOCABULARY = frozenset(_WORDS.split())  # the narrator's own words


class Check(NamedTuple):
    ok: bool
    missing: tuple[str, ...]  # critical fields the sentence doesn't say
    invented: tuple[str, ...]  # words that come from nowhere in the request


def words(text: str) -> list[str]:
    """Lower-case words, with punctuation dropped: "Push main, as a force push." is 6 words."""
    return re.sub(r"[^\w\s]", " ", text.lower()).split()


def check(sentence: str, session: str, actions: Iterable[Action]) -> Check:
    said = f" {' '.join(words(sentence))} "
    fields = [field for action in actions for field in action.fields]
    missing = tuple(
        f"{f.name}: {f.spoken}" for f in fields if f" {' '.join(words(f.spoken))} " not in said
    )
    allowed = VOCABULARY | set(words(session)) | {w for f in fields for w in words(f.spoken)}
    invented = tuple(dict.fromkeys(w for w in words(sentence) if w not in allowed))
    return Check(not missing and not invented, missing, invented)
