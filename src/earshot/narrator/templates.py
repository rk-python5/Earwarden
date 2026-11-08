"""The template narrator: one short sentence per request, written by rules (Phases 1 and 2).

The policy engine's reading of a request (`policy.fields`) gives each action and its critical
fields; the narrator says one clause per action ("run the tests, then push feature to origin").
Secrets are redacted first. Then the fidelity checker (`checker`) makes sure every critical field
is said and nothing is invented, and a sentence longer than 25 words isn't spoken at all: either
way, the request waits on the screen instead.
"""

from __future__ import annotations

from typing import Any, NamedTuple

from earshot.narrator import checker, redact, spoken
from earshot.policy import bash, fields
from earshot.policy.engine import Judgement

MAX_WORDS = 25


class Narration(NamedTuple):
    text: str
    fits: bool  # False when the request can't be said faithfully, in few enough words
    problem: str | None = None  # why it doesn't fit, for the audit log


def _clause(action: fields.Action, chained: bool) -> str:
    d = action.detail
    if action.kind == "push":
        if d["branches"]:
            clause = f"push {' and '.join(d['branches'])} to {d['remote']}"
            if d["deletes"]:
                clause += f", and delete {' and '.join(d['deletes'])}"
        else:
            clause = f"delete {' and '.join(d['deletes'])} on {d['remote']}"
        return clause + (", as a force push" if d["force"] else "")
    if action.kind == "install":
        clause = f"install {', '.join(d['packages'])}"
        return clause + (f", from the index at {d['index']}" if d["index"] else "")
    if action.kind == "delete":
        return f"delete {', '.join(d['targets'])}" + (", recursively" if d["recursive"] else "")
    if action.kind == "network":
        return f"{d['verb']} {d['domain']}"
    if action.kind in ("write", "edit", "read"):
        return f"{action.kind} {d['path']}"
    if action.kind == "mcp":
        on = f", on {d['argument']}" if d["argument"] else ""
        return f"use {d['tool']} from {d['server']}{on}"
    if action.kind == "tests":
        return "run the tests"
    if action.kind == "search":
        return "search the web"
    if action.kind == "run":
        return f"run {d['command']}" if chained else f"run: {d['command']}"
    return f"use {spoken.identifier(d['tool'])}"


def narrate(
    session: str,
    cwd: str,
    tool_name: str,
    tool_input: dict[str, Any],
    judgement: Judgement | None = None,
) -> Narration:
    """What to say about one request. Secrets are already replaced with "a secret value"."""
    who = spoken.identifier(session)
    assessment = judgement.bash if judgement else None
    if tool_name == "Bash" and assessment is None:
        command = tool_input.get("command")
        assessment = bash.assess(command, cwd) if isinstance(command, str) else None
    actions = fields.actions(tool_name, tool_input, cwd, assessment)
    clauses = [_clause(action, len(actions) > 1) for action in actions]
    text = redact.redact(f"{who} wants to {', then '.join(clauses)}.", redact.SPOKEN)
    if len(text.split()) > MAX_WORDS:
        return Narration(f"{who} has a long request waiting.", False, "narrator: too long to say")
    result = checker.check(text, who, actions)
    if not result.ok:
        problem = "; ".join([*(f"missing {m}" for m in result.missing), *result.invented])
        return Narration(f"{who} has a request waiting.", False, f"checker: {problem}")
    return Narration(text, True)
