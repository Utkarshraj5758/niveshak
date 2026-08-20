"""Tests for final-score assembly: blend math, band thresholds, top-3, and the no-advice rule.

Uses `build_risk_score` (pure) so no DB/model is needed. The concrete numbers match the
worked examples in docs/DECISIONS.md D1.
"""

from datetime import datetime, timezone

from niveshak.parse.tip import Tip
from niveshak.score import assemble as A


def _tip(**over) -> Tip:
    base = dict(
        tip_id="t1", source="telegram", raw_text="x", language="en",
        ticker="SUZLON", direction="long", target_price=None, horizon_days=None,
        urgency="low", guarantee_claim=False, insider_claim=False,
        disclosure_present=True, posted_at=datetime(2026, 8, 20, tzinfo=timezone.utc),
    )
    base.update(over)
    return Tip(**base)


def _scammy(**over) -> Tip:
    return _tip(guarantee_claim=True, insider_claim=True, disclosure_present=False,
                urgency="high", target_price=80.0, **over)


SUSCEPTIBLE = {"runup_20d": 2.0, "upper_circuit_count_10d": 8, "liquidity_bucket": "micro",
               "is_sme": True, "volume_zscore_60d": 5.0, "days_since_listing": 40.0}


def test_band_thresholds():
    assert A.band_for(0) == "low"
    assert A.band_for(24) == "low"
    assert A.band_for(25) == "elevated"
    assert A.band_for(59) == "elevated"
    assert A.band_for(60) == "high"
    assert A.band_for(100) == "high"


def test_scammy_on_ordinary_data_is_elevated_not_high():
    """The headline case from DECISIONS D1: textbook-scammy message, ordinary scrip."""
    rs = A.build_risk_score(_scammy(), model_susceptibility=0.0, feature_row={})
    assert rs.value == 40
    assert rs.band == "elevated"          # cannot reach 'high' on message alone — by design
    # message reasons still surface the manipulation
    assert any("guaranteed" in c.reason.lower() for c in rs.contributions)


def test_scammy_on_susceptible_scrip_is_high():
    rs = A.build_risk_score(_scammy(), model_susceptibility=0.48, feature_row=SUSCEPTIBLE)
    assert rs.value == 69
    assert rs.band == "high"
    # the market half is now a top driver, explained by behavioural callouts (no advice)
    market = [c for c in rs.contributions if c.half == "market"]
    assert market and "pump-prone" in market[0].reason


def test_clean_disclosed_ordinary_is_low():
    rs = A.build_risk_score(_tip(), model_susceptibility=0.0, feature_row={})
    assert rs.value == 0
    assert rs.band == "low"
    assert rs.contributions == []


def test_unresolved_ticker_is_message_only_with_note():
    rs = A.build_risk_score(_scammy(ticker=None), model_susceptibility=0.0, feature_row=None)
    assert rs.value == 40 and rs.band == "elevated"
    assert rs.confidence == 0.5
    assert any("could not be resolved" in n for n in rs.notes)


def test_only_top_three_contributions():
    rs = A.build_risk_score(_scammy(), model_susceptibility=0.48, feature_row=SUSCEPTIBLE)
    assert len(rs.contributions) == 3
    impacts = [c.impact for c in rs.contributions]
    assert impacts == sorted(impacts, reverse=True)


def test_impacts_are_consistent_with_value():
    """Displayed top-3 impacts must be a subset of the total; full set sums to the score."""
    tip = _scammy()
    rs = A.build_risk_score(tip, model_susceptibility=0.48, feature_row=SUSCEPTIBLE)
    # market(28.8) + guarantee(12) + insider(12) + missing_disc(6) + urgency(6) + target(4) = 68.8 ~ 69
    assert abs(rs.value - 68.8) <= 1


def test_no_contribution_reason_reads_as_advice():
    rs = A.build_risk_score(_scammy(), model_susceptibility=0.48, feature_row=SUSCEPTIBLE)
    banned = ("buy", "sell", "hold", "avoid", "invest", "book profit", "exit", "target price")
    for c in rs.contributions:
        low = c.reason.lower()
        assert not any(b in low for b in banned), f"advice-like reason: {c.reason!r}"


def test_disclaimer_present():
    rs = A.build_risk_score(_scammy(), 0.0, {})
    assert "not investment advice" in rs.disclaimer.lower()


def _burst(is_burst=True):
    from niveshak.graph.burst import BurstStat
    return BurstStat("SUZLON", n_channels=5, baseline_mean=0.5, baseline_std=0.5, z=9.0) if is_burst \
        else BurstStat("SUZLON", n_channels=1, baseline_mean=1.0, baseline_std=1.0, z=0.0)


def test_coordination_burst_adds_bounded_points_and_reason():
    base = A.build_risk_score(_scammy(), 0.0, {})
    with_burst = A.build_risk_score(_scammy(), 0.0, {}, burst=_burst())
    assert with_burst.value == base.value + A.COORD_MAX_POINTS   # capped at +15
    assert any(c.code == "coordination_burst" for c in with_burst.contributions)
    reason = next(c.reason for c in with_burst.contributions if c.code == "coordination_burst")
    assert "channels within 48h" in reason
    # still no advice language
    for banned in ("buy", "sell", "avoid", "invest"):
        assert banned not in reason.lower()


def test_non_burst_adds_nothing():
    base = A.build_risk_score(_scammy(), 0.0, {})
    same = A.build_risk_score(_scammy(), 0.0, {}, burst=_burst(is_burst=False))
    assert same.value == base.value
    assert all(c.code != "coordination_burst" for c in same.contributions)
