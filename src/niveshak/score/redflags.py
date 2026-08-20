"""Message red-flag scorer — the 0.4-weight half of the final score (BUILD_PLAN, SPEC §3.7).

Transparent, weighted rules over a parsed `Tip`. Each rule carries a FIXED, DOCUMENTED weight
and its own human-readable reason string. The reasons are the product's legal footing, not a
style choice:

    Every reason describes the MESSAGE ("claims a guaranteed target", "no SEBI disclosure"),
    never the stock. Nothing here may read as a buy / sell / hold / avoid call. Niveshak
    judges how a *message* behaves, not whether a *security* is good — that is what keeps us
    out of SEBI investment-adviser territory (CLAUDE.md rule 1).

The weights are a documented product decision. They sum to 1.0, so the message half is a
clean 0..1 score with no capping needed. Combining it with the model half (0.6/0.4) is done
in the score-assembly step, not here.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel

from niveshak.parse.tip import Tip


class Contribution(BaseModel):
    """One triggered red flag: a stable code, its fixed weight, and a message-level reason."""

    code: str
    weight: float
    reason: str


@dataclass(frozen=True)
class _Rule:
    code: str
    weight: float
    reason: str
    triggered: Callable[[Tip], bool]


# The rule table. Weights are fixed and sum to 1.0. Reasons are strictly about the message.
RED_FLAG_RULES: tuple[_Rule, ...] = (
    _Rule(
        "guarantee_language", 0.30,
        "Message claims a guaranteed or 'sure-shot' outcome",
        lambda t: t.guarantee_claim,
    ),
    _Rule(
        "insider_language", 0.30,
        "Message claims access to insider or operator information",
        lambda t: t.insider_claim,
    ),
    _Rule(
        "missing_disclosure", 0.15,
        "Message carries no SEBI research-analyst disclosure",
        lambda t: not t.disclosure_present,
    ),
    _Rule(
        "high_urgency", 0.15,
        "Message uses high-pressure, act-now urgency",
        lambda t: t.urgency == "high",
    ),
    _Rule(
        "explicit_target", 0.10,
        "Message states a specific price target",
        lambda t: t.target_price is not None,
    ),
)

# Safety net: no reason may read as investment advice. Enforced by a test too.
_FORBIDDEN_IN_REASON = ("buy", "sell", "hold", "avoid", "invest", "book profit", "exit")


class RedFlagResult(BaseModel):
    score: float                       # 0..1, sum of triggered weights
    contributions: list[Contribution]  # only the flags that fired, weight-desc


def score_red_flags(tip: Tip) -> RedFlagResult:
    """Apply every red-flag rule to a Tip. Returns the 0..1 message score + fired flags."""
    fired = [r for r in RED_FLAG_RULES if r.triggered(tip)]
    fired.sort(key=lambda r: r.weight, reverse=True)
    contributions = [Contribution(code=r.code, weight=r.weight, reason=r.reason) for r in fired]
    score = round(min(1.0, sum(r.weight for r in fired)), 4)
    return RedFlagResult(score=score, contributions=contributions)
