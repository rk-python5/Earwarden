"""The risk-gate interface: a score that can only raise a tier (Phase 4, milestone 4).

The spec's third step in choosing a tier: "the risk gate's score, when it's running: final tier
= the higher of the rule tier and the gate tier." No gate ships in 1.0; this is the slot, with
the rules that keep it safe:

- A gate returns a score from 0 to 1 and reason codes. The score maps to a tier, and the final
  tier is the higher of the two. Nothing a gate says can lower a tier, and tier 3 stays tier 3.
- A gate that fails, hangs or returns nonsense changes nothing. Its call has a time limit.
- Spoken reasons come from a closed list of phrases. A code outside it is logged, not spoken, so
  a model behind a gate can't talk through the speaker.
"""

from __future__ import annotations

import concurrent.futures
import logging
from typing import Any, Protocol

from pydantic import ValidationError

from earwarden import contracts
from earwarden.policy.engine import Judgement

log = logging.getLogger("earwarden.risk")

TIER_2_FROM = 0.5  # a score at least this high raises to tier 2
TIER_3_FROM = 0.85  # and this high to tier 3
TIME_LIMIT_S = 0.3

# The closed list: a gate speaks only through these.
SPOKEN_REASONS: dict[str, str] = {
    "unusual_target": "an unusual target",
    "new_dependency": "a new dependency",
    "secrets_nearby": "secrets nearby",
    "broad_change": "a broad change",
    "destructive": "a destructive command",
    "network": "a network call",
    "unknown_host": "an unknown host",
    "off_hours": "the time of day",
    "unfamiliar_repo": "an unfamiliar repository",
    "privilege": "elevated privileges",
}


class Gate(Protocol):
    def score(self, tool_name: str, tool_input: dict[str, Any], cwd: str) -> Any: ...


def tier_for(score: float) -> int:
    if score >= TIER_3_FROM:
        return 3  # never by voice, like the floor
    if score >= TIER_2_FROM:
        return 2
    return 0  # below the rules' lowest: never raises


def spoken(reasons: tuple[str, ...]) -> str:
    """The reasons as phrases from the closed list; unknown codes are logged and left out."""
    phrases = []
    for code in reasons:
        if code in SPOKEN_REASONS:
            phrases.append(SPOKEN_REASONS[code])
        else:
            log.warning("a gate gave a reason outside the spoken list: %r", code[:80])
    if not phrases:
        return ""
    if len(phrases) == 1:
        return phrases[0]
    return ", ".join(phrases[:-1]) + f" and {phrases[-1]}"


def merge(judgement: Judgement, result: contracts.GateScore | None) -> Judgement:
    """The judgement with the gate's view: the higher tier, and a rule that says why."""
    if result is None:
        return judgement
    gate_tier = tier_for(result.score)
    tier = max(judgement.tier, gate_tier)
    why = spoken(result.reasons)
    rule = f"gate: {result.score:.2f}" + (f", {why}" if why else "")
    if tier > judgement.tier:
        rule += f": tier {judgement.tier} raised to {tier}"
    raised = why if tier > judgement.tier else judgement.raised
    return judgement._replace(tier=tier, rules=(*judgement.rules, rule), raised=raised)


def ask(
    gate: Gate, tool_name: str, tool_input: dict[str, Any], cwd: str
) -> contracts.GateScore | None:
    """The gate's score, or None if it failed, hung or returned something that isn't one."""
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        future = pool.submit(gate.score, tool_name, tool_input, cwd)
        raw = future.result(timeout=TIME_LIMIT_S)
    except concurrent.futures.TimeoutError:
        log.warning("the risk gate took longer than %.1f s; ignored", TIME_LIMIT_S)
        return None
    except Exception:
        log.exception("the risk gate failed; ignored")
        return None
    finally:
        pool.shutdown(wait=False)
    try:
        if isinstance(raw, contracts.GateScore):
            return raw
        if isinstance(raw, dict):
            reasons = raw.get("reasons", ())
            if isinstance(reasons, list):
                raw = {**raw, "reasons": tuple(reasons)}
            return contracts.GateScore.model_validate(raw)
    except ValidationError:
        pass
    log.warning("the risk gate returned something that isn't a score; ignored")
    return None


def apply(
    gate: Gate | None, judgement: Judgement, tool_name: str, tool_input: dict[str, Any], cwd: str
) -> Judgement:
    """The judgement after the gate, if there is one. Never lower, and never from a failure."""
    if gate is None:
        return judgement
    merged = merge(judgement, ask(gate, tool_name, tool_input, cwd))
    if merged.tier < judgement.tier:  # can't happen; belt and braces for the invariant
        return judgement
    return merged
