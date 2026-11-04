"""Phrase lists and reference intent rules shared by the Step 0 speech scripts."""

from __future__ import annotations

import re
from typing import NamedTuple

# Spoken summaries in the plan's style, in spoken form, as the template narrator would say them.
SUMMARIES = [
    "API wants to push feature slash login to origin. To push, say: approve orchard.",
    "Docs wants to edit quickstart dot m d, in the docs folder. Nod or say yes.",
    "API wants to install requests, version 2.32.3. To install, say: approve lantern.",
    "R-E-Q-E-U-S-T-S. This looks like requests. It's on your screen.",
    "Deploy wants to run the tests. Nod or say yes.",
    "API wants to reach example dot com, sending data. To allow, say: approve harbor.",
    "API has a long command waiting; it's on your screen.",
    "API and docs finished.",
    "Three sessions. API: running 12 minutes, tests passing. Docs: waiting for you. "
    "Deploy: finished 5 minutes ago.",
    "Docs approval moved to your screen.",
]

# Words that reach a summary when the normaliser doesn't spell them out: package names (including
# lookalikes), branches, files and tools. Each must come out of the text front-end with phonemes,
# or Kokoro skips it silently (decisions.md, P-03).
IDENTIFIERS = [
    # Popular packages and two lookalikes
    "requests",
    "reqeusts",
    "numpy",
    "pandas",
    "boto3",
    "botocore",
    "urllib3",
    "pydantic",
    "fastapi",
    "uvicorn",
    "httpx",
    "aiohttp",
    "sqlalchemy",
    "pytest",
    "pyyaml",
    "pyaml",
    "setuptools",
    "tomli",
    "tomlkit",
    "rich",
    "typer",
    "ruff",
    "mypy",
    "black",
    "isort",
    "jinja2",
    "werkzeug",
    "flask",
    "django",
    "celery",
    "redis",
    "psycopg2",
    "grpcio",
    "protobuf",
    "torch",
    "transformers",
    "openai",
    "anthropic",
    "langchain",
    "tiktoken",
    "mlx",
    "kokoro",
    "parakeet",
    "earshot",
    "numpyy",
    "djnago",
    # Git words and branches
    "origin",
    "upstream",
    "main",
    "HEAD",
    "rebase",
    "squash",
    "feature/login-v2",
    "hotfix/oauth-callback",
    "release/2.4",
    "dependabot/npm_and_yarn/lodash-4.17.21",
    # Files and folders
    "README.md",
    "conftest.py",
    "pyproject.toml",
    "package.json",
    "Makefile",
    "Dockerfile",
    ".env",
    ".envrc",
    "id_ed25519",
    "routes.py",
    "src/api",
    "node_modules",
    # Tools and commands
    "npm",
    "pnpm",
    "yarn",
    "brew",
    "uv",
    "pip",
    "kubectl",
    "terraform",
    "nginx",
    "curl",
    "wget",
    "jq",
    "rsync",
    "chmod",
    "sudo",
    "zsh",
    "gh",
    "localhost",
    "webhook",
]


class Reply(NamedTuple):
    """One reply to record: what to say, what it should mean, and the challenge word if any."""

    id: str
    text: str
    intent: str
    challenge: str | None = None


# Ten challenge words, pairwise at least two Double Metaphone edits apart (decisions.md, P-08).
CHALLENGE_WORDS = [
    "orchard",
    "lantern",
    "harbor",
    "copper",
    "juniper",
    "ribbon",
    "marble",
    "compass",
    "tunnel",
    "glacier",
]

# Session names a reply can address ("API, yes").
SESSIONS = ["api", "docs", "deploy"]

REPLIES = [
    # Plain answers, from the plan's intent table
    Reply("yes", "yes", "approve"),
    Reply("yeah", "yeah", "approve"),
    Reply("go-ahead", "go ahead", "approve"),
    Reply("approve", "approve", "approve"),
    Reply("do-it", "do it", "approve"),
    Reply("yep", "yep", "approve"),
    Reply("approve-it", "approve it", "approve"),
    Reply("yes-please", "yes please", "approve"),
    Reply("no", "no", "deny"),
    Reply("nope", "nope", "deny"),
    Reply("stop", "stop", "deny"),
    Reply("deny", "deny", "deny"),
    Reply("cancel", "cancel", "deny"),
    Reply("wait", "wait", "wait"),
    Reply("hold-on", "hold on", "wait"),
    Reply("later", "later", "wait"),
    # Instructions: a deny with a message for the agent
    Reply("poetry", "no, use poetry instead", "instruction"),
    Reply("staging", "no, push to staging", "instruction"),
    Reply("yes-but", "yes, but run the tests first", "instruction"),
    # Approval words inside a refusal (P-07): none of these may approve
    Reply("dont-do-it", "don't do it", "deny"),
    Reply("no-dont", "no, don't", "deny"),
    Reply("dont-approve", "don't approve that", "deny"),
    Reply("do-it-later", "do it later", "wait"),
    Reply("not-yet", "not yet", "wait"),
    # Off-list answers: no approval, ask again
    Reply("okay", "okay", "unclear"),
    Reply("sure", "sure", "unclear"),
    Reply("hmm", "hmm", "unclear"),
    Reply("what-was-that", "what was that", "unclear"),
    # Addressing a session
    Reply("api-yes", "API, yes", "approve"),
    Reply("deploy-yes", "deploy, yes", "approve"),
    Reply("docs-no", "docs, no", "deny"),
    Reply("docs-one", "the docs one", "route"),
    # Push-to-talk commands
    Reply("status", "status", "command"),
    Reply("repeat", "repeat", "command"),
    Reply("details", "details", "command"),
    Reply("quiet-mode", "quiet mode", "command"),
    # Tier-2 challenge phrases
    *(Reply(f"ch-{word}", f"approve {word}", "approve", word) for word in CHALLENGE_WORDS),
    # Decoys one Double Metaphone edit from the real word: must not approve (P-08)
    Reply("decoy-orchid", "approve orchid", "unclear", "orchard"),
    Reply("decoy-cobbler", "approve cobbler", "unclear", "copper"),
    Reply("wrong-word", "approve lantern", "unclear", "harbor"),
    # A bare yes where a challenge phrase is required
    Reply("bare-yes-t2", "yes", "unclear", "compass"),
]

# Reference intent rules for the spike: the plan's intent table, with the whole-utterance matching
# proposed in P-07. An approval needs the entire reply to match; nothing else ever approves.
APPROVE = {"yes", "yeah", "yep", "go ahead", "approve", "do it", "approve it", "yes please"}
DENY = {"no", "nope", "stop", "deny", "cancel"}
WAIT = {"wait", "hold on", "later", "not yet"}
COMMANDS = {"status", "repeat", "details", "quiet mode", "focus mode", "chatty mode"}
NEGATIONS = {"no", "nope", "not", "don't", "dont", "never", "stop", "cancel", "deny"}


def normalize(text: str) -> str:
    """Lower-case, curly apostrophes made straight, other punctuation dropped."""
    text = text.lower().replace("\N{RIGHT SINGLE QUOTATION MARK}", "'")
    return " ".join(re.sub(r"[^\w' ]+", " ", text).split())


def intent(text: str, challenge: str | None = None) -> str:
    """approve, deny, instruction, wait, command, route or unclear."""
    words = normalize(text).split()
    if len(words) > 1 and words[0] in SESSIONS:  # "API, yes" answers the API session
        words = words[1:]
    phrase = " ".join(words)
    if challenge is not None:  # tier 2: only the exact challenge phrase approves
        if phrase == f"approve {challenge}":
            return "approve"
        return "deny" if phrase in DENY else "unclear"
    route = re.fullmatch(r"the (\w+) one", phrase)
    if route and route.group(1) in SESSIONS:
        return "route"
    for name, phrases in (
        ("approve", APPROVE),
        ("deny", DENY),
        ("wait", WAIT),
        ("command", COMMANDS),
    ):
        if phrase in phrases:
            return name
    if words and words[0] in {"no", "nope"}:  # "no, use poetry instead"
        return "deny" if all(w in NEGATIONS for w in words[1:]) else "instruction"
    if words[:1] == ["yes"] and "but" in words:  # "yes, but…" is an instruction, never approval
        return "instruction"
    if "later" in words or "wait" in words:
        return "wait"
    if any(w in NEGATIONS for w in words):
        return "deny"
    return "unclear"


# P-08 (revised after the Mac runs): the recogniser rarely hears "approve" itself, but usually gets
# the challenge word right. These are the variants it produced for "approve".
CARRIER_VARIANTS = re.compile(r"^(approved|approves|a proof|a prove)\b")
# Spellings the recogniser may use for a challenge word.
SPELLINGS = {"harbour": "harbor"}


def with_carrier_variants(text: str) -> str:
    """Read "approved" and "a proof" at the start of a reply as "approve"."""
    return CARRIER_VARIANTS.sub("approve", normalize(text))


def challenge_word_intent(text: str, challenge: str | None) -> str:
    """Let the challenge word decide: it must end a reply of four words or fewer, with no negation.

    Without a challenge this is the plain whole-reply rule (P-07). It's only safe if no two
    challenge words sound alike, because the recogniser can turn one into the other (P-08).
    """
    if challenge is None:
        return intent(text)
    words = normalize(text).split()
    if words and len(words) <= 4 and not NEGATIONS.intersection(words):
        last = SPELLINGS.get(words[-1], words[-1])
        if last in (challenge, challenge + "s"):
            return "approve"
    return intent(text, challenge)
