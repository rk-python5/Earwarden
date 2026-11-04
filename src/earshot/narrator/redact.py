"""Secret redaction, before anything is spoken or logged (an invariant; D-019 for Phase 1).

Pattern detectors catch the common token formats and credentials in URLs and assignments; an
entropy check catches long random strings. Phase 2 tunes it against a corpus.
"""

from __future__ import annotations

import math
import re
from collections import Counter

SPOKEN = "a secret value"
LOGGED = "[REDACTED]"

# Each pattern's group "s" is the secret; the rest of the match is kept.
PATTERNS = [
    re.compile(r"(?P<s>\bAKIA[0-9A-Z]{16}\b)"),  # AWS access key id
    re.compile(r"(?P<s>\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,})"),  # GitHub tokens
    re.compile(r"(?P<s>\bgithub_pat_[A-Za-z0-9_]{40,})"),
    re.compile(r"(?P<s>\bsk-[A-Za-z0-9_-]{20,})"),  # OpenAI, Anthropic and similar
    re.compile(r"(?P<s>\bxox[abprs]-[A-Za-z0-9-]{10,})"),  # Slack
    re.compile(r"(?P<s>\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})"),  # JWT
    re.compile(
        r"(?P<s>-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|$))"
    ),
    re.compile(r"(?i)\bbearer\s+(?P<s>[A-Za-z0-9._~+/=-]{16,})"),
    re.compile(r"://[^/\s:@]+:(?P<s>[^/\s@]+)@"),  # the password in user:password@host
    re.compile(
        r"(?i)\b(?:password|passwd|pwd|secret|token|api_key|apikey|access_key)\s*[=:]\s*"
        r"(?P<s>[^\s&\"']{4,})"
    ),
]
# No slash: a long path is not a key, and paths are full of mixed-case and digits.
CANDIDATE = re.compile(r"[A-Za-z0-9+_=-]{32,}")


def _entropy(text: str) -> float:
    counts = Counter(text)
    return -sum(n / len(text) * math.log2(n / len(text)) for n in counts.values())


def _random_looking(token: str) -> bool:
    """Long, mixed and high-entropy: a key, not a word or a path."""
    classes = sum(bool(re.search(p, token)) for p in (r"[a-z]", r"[A-Z]", r"[0-9]"))
    return classes >= 2 and _entropy(token) >= 4.0


def redact(text: str, replacement: str = LOGGED) -> str:
    for pattern in PATTERNS:
        text = pattern.sub(
            lambda m: (
                m.group()[: m.start("s") - m.start()]
                + replacement
                + m.group()[m.end("s") - m.start() :]
            ),
            text,
        )
    return CANDIDATE.sub(lambda m: replacement if _random_looking(m.group()) else m.group(), text)


def contains_secret(text: str) -> bool:
    return redact(text, "\0") != text
