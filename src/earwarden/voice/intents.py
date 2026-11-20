"""What an answer means, by rules only (D-024: exact whole-reply matches, no session names).

Ported from the Step 0 speech spike's rules, which never approved a non-approval in 200
recognitions of rehaan's recordings. Phase 1 has no challenge phrases; those come in Phase 2.
"""

from __future__ import annotations

import re
from typing import Literal, NamedTuple

Kind = Literal["approve", "deny", "instruction", "wait", "unclear"]

APPROVE = {"yes", "yeah", "yep", "go ahead", "approve", "do it", "approve it", "yes please"}
DENY = {"no", "nope", "stop", "deny", "cancel"}
WAIT = {"wait", "hold on", "later", "not yet"}
NEGATIONS = {"no", "nope", "not", "don't", "dont", "never", "stop", "cancel", "deny"}


class Intent(NamedTuple):
    kind: Kind
    message: str | None = None  # for an instruction: what to tell the agent


def normalize(text: str) -> str:
    """Lower-case, curly apostrophes made straight, other punctuation dropped."""
    text = text.lower().replace("\N{RIGHT SINGLE QUOTATION MARK}", "'")
    return " ".join(re.sub(r"[^\w' ]+", " ", text).split())


def parse(transcript: str) -> Intent:
    words = normalize(transcript).split()
    phrase = " ".join(words)
    if phrase in APPROVE:
        return Intent("approve")
    if phrase in DENY:
        return Intent("deny")
    if phrase in WAIT:
        return Intent("wait")
    if words and words[0] in {"no", "nope"}:  # "no, use poetry instead"
        if all(w in NEGATIONS for w in words[1:]):
            return Intent("deny")
        rest = re.sub(r"^\s*(no|nope)\b[\s,.;:!-]*", "", transcript.strip(), flags=re.IGNORECASE)
        return Intent("instruction", rest or None)
    if words[:1] == ["yes"] and "but" in words:  # "yes, but…" never approves
        return Intent("instruction", transcript.strip())
    if "later" in words or "wait" in words:
        return Intent("wait")
    if any(w in NEGATIONS for w in words):
        return Intent("deny")
    return Intent("unclear")
