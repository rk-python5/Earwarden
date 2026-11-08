"""Challenge words for tier 2 (Phase 2, milestone 5; P-08 revised, D-029).

A tier-2 request is approved by voice only with a fresh word: "To install, say: approve orchard."

- The word is picked at random for each request from about 200 (`voice/data/challenge-words.txt`,
  built by `dev/build_challenge_words.py`). They're chosen so no two sound alike: their Double
  Metaphone codes are at least 2 edits apart, and as far from the words people say in replies.
- A reply matches when its last word has the challenge word's code, so an accent, or "harbour" for
  "harbor", still matches. The reply must be four words or fewer, with no negation. The carrier
  word "approve" is ignored: the recogniser rarely hears it right, and it's only there to give the
  voiceprint enough speech.

A matching reply still needs the voiceprint (milestone 6) before anything is approved.
"""

from __future__ import annotations

import re
import secrets
from functools import cache
from pathlib import Path

from earshot.voice import intents

WORDS_FILE = Path(__file__).parent / "data" / "challenge-words.txt"
MAX_REPLY_WORDS = 4
MIN_CODE_DISTANCE = 2

# What people say to Earshot, and other everyday words a challenge word mustn't sound like.
_EVERYDAY = """
approve allow yes no okay sure please thanks sorry what again repeat details status quiet
mode focus chatty later wait hold on go ahead do it not yet never stop cancel deny one two
three four five six seven eight nine ten eleven twelve twenty hundred thousand the a and or
but if then so this that it is was be have has had do does did will would can could should
may might must shall here there now today tomorrow yesterday morning night time day week
month year good bad right wrong left up down in out over under push pull install run test
build deploy commit merge branch main master origin delete remove file folder project
request session claude earshot api docs hello hey hi
"""
EVERYDAY = frozenset(
    intents.APPROVE | intents.DENY | intents.WAIT | intents.NEGATIONS | set(_EVERYDAY.split())
)


def codes(word: str) -> frozenset[str]:
    """A word's Double Metaphone codes, primary and alternate, ignoring case and punctuation."""
    from metaphone import doublemetaphone

    letters = re.sub(r"[^a-z]", "", word.lower())
    return frozenset(code for code in doublemetaphone(letters) if code) if letters else frozenset()


def code_distance(a: str, b: str) -> int:
    """The fewest edits between two words' codes, over their primary and alternate codes."""
    return min(
        (_edits(x, y) for x in codes(a) for y in codes(b)),
        default=max(len(a), len(b)),
    )


def _edits(a: str, b: str) -> int:
    row = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(row[j] + 1, current[j - 1] + 1, row[j - 1] + (ca != cb)))
        row = current
    return row[-1]


@cache
def words() -> tuple[str, ...]:
    lines = WORDS_FILE.read_text(encoding="utf-8").splitlines()
    return tuple(line.strip() for line in lines if line.strip() and not line.startswith("#"))


def pick() -> str:
    """A challenge word nobody can predict."""
    return secrets.choice(words())


def matches(transcript: str, word: str) -> bool:
    """Whether a reply says the challenge `word`, by P-08's rule."""
    said = intents.normalize(transcript).split()
    if not said or len(said) > MAX_REPLY_WORDS:
        return False
    if any(w in intents.NEGATIONS for w in said):
        return False
    return bool(codes(said[-1]) & codes(word))
