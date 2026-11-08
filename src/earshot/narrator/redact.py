"""Secret redaction, before anything is spoken or logged (an invariant; D-019 for Phase 1).

Pattern detectors catch the common token formats, and credentials in URLs, assignments and
`--password VALUE` options; an entropy check catches long random strings. A corpus of real-looking
keys and near-misses (`tests/test_redaction.py`) keeps both honest (Phase 2, milestone 3).
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
    re.compile(r"(?P<s>\bglpat-[A-Za-z0-9_-]{20,})"),  # GitLab
    re.compile(r"(?P<s>\bxapp-[0-9]-[A-Za-z0-9-]{10,})"),  # Slack app-level
    re.compile(r"(?P<s>\b(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]{16,})"),  # Stripe
    re.compile(r"(?P<s>\bAIza[0-9A-Za-z_-]{35})"),  # Google API key
    re.compile(r"(?P<s>\bSG\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,})"),  # SendGrid
    re.compile(r"(?P<s>\bnpm_[A-Za-z0-9]{36})"),  # npm
    re.compile(r"(?P<s>\bpypi-[A-Za-z0-9_-]{50,})"),  # PyPI
    re.compile(r"(?P<s>\bhf_[A-Za-z0-9]{30,})"),  # Hugging Face
    re.compile(r"(?P<s>\bSK[0-9a-fA-F]{32}\b)"),  # Twilio API key
    re.compile(r"://[^/\s:@]+:(?P<s>[^/\s@]+)@"),  # the password in user:password@host
    # NAME=value where NAME holds a secret word: password, AWS_SECRET_ACCESS_KEY, GITHUB_TOKEN.
    # Not max_tokens=1000: the secret word must end the name or be followed by _ or -.
    re.compile(
        r"(?i)(?<![A-Za-z0-9])(?:[A-Za-z0-9]+[_-])*"
        r"(?:password|passwd|pwd|passphrase|secret|token|api[_-]?key|apikey|access[_-]?key|"
        r"private[_-]?key|account[_-]?key|client[_-]?secret|auth[_-]?token|session[_-]?key)"
        r"(?:[_-][A-Za-z0-9_-]*)?[\"']?\s*[=:]\s*[\"']?(?P<s>(?!\d+\b)[^\s&\"'\\,;]{4,})"
    ),
    re.compile(r"(?i)--(?:password|passwd|token|api-key|secret)[ =](?P<s>[^\s\"']{4,})"),
    re.compile(r"(?i)aws_secret_access_key[\"']?\s+[\"']?(?P<s>[A-Za-z0-9/+=]{40})"),
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
