"""Tests for the weighted red-flag scorer — one hand-written tip per rule.

Also enforces, in code, the non-negotiable: no reason string may read as investment advice.
"""

from datetime import datetime, timezone

from niveshak.parse.tip import Tip
from niveshak.score import redflags as RF


def _tip(**over) -> Tip:
    base = dict(
        tip_id="t1", source="telegram", raw_text="x", language="en",
        ticker="SUZLON", direction="long", target_price=None, horizon_days=None,
        urgency="low", guarantee_claim=False, insider_claim=False,
        disclosure_present=True,     # disclosed by default -> missing_disclosure won't fire
        posted_at=datetime(2026, 8, 20, tzinfo=timezone.utc),
    )
    base.update(over)
    return Tip(**base)


def test_clean_tip_scores_zero():
    res = RF.score_red_flags(_tip())
    assert res.score == 0.0
    assert res.contributions == []


def test_guarantee_flag():
    res = RF.score_red_flags(_tip(guarantee_claim=True))
    assert res.score == 0.30
    assert [c.code for c in res.contributions] == ["guarantee_language"]


def test_insider_flag():
    res = RF.score_red_flags(_tip(insider_claim=True))
    assert res.score == 0.30
    assert res.contributions[0].code == "insider_language"


def test_missing_disclosure_flag():
    res = RF.score_red_flags(_tip(disclosure_present=False))
    assert res.score == 0.15
    assert res.contributions[0].code == "missing_disclosure"


def test_high_urgency_flag():
    res = RF.score_red_flags(_tip(urgency="high"))
    assert res.score == 0.15
    assert res.contributions[0].code == "high_urgency"


def test_explicit_target_flag():
    res = RF.score_red_flags(_tip(target_price=80.0))
    assert res.score == 0.10
    assert res.contributions[0].code == "explicit_target"


def test_worst_case_all_flags_sum_to_one():
    res = RF.score_red_flags(_tip(
        guarantee_claim=True, insider_claim=True, disclosure_present=False,
        urgency="high", target_price=80.0,
    ))
    assert res.score == 1.0
    assert len(res.contributions) == 5
    # sorted by weight descending
    weights = [c.weight for c in res.contributions]
    assert weights == sorted(weights, reverse=True)


def test_reasons_describe_message_never_advice():
    """No reason may read as a buy/sell/hold/avoid call — the product's legal footing."""
    for rule in RF.RED_FLAG_RULES:
        low = rule.reason.lower()
        for banned in RF._FORBIDDEN_IN_REASON:
            assert banned not in low, f"rule {rule.code} reason reads as advice: {rule.reason!r}"
        assert "message" in low          # every reason is about the message


def test_weights_sum_to_one():
    assert round(sum(r.weight for r in RF.RED_FLAG_RULES), 4) == 1.0
