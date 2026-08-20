"""Final score assembly: 0.6·model + 0.4·red_flags -> a banded, explained RiskScore.

See docs/DECISIONS.md D1 for why the split is what it is and why message-signal-alone tops
out in the "elevated" band. The blend weights and band thresholds are documented product
decisions, not fitted parameters.

The market half (model susceptibility) is explained WITHOUT SHAP (deliberately cut): the
model probability sets the market impact, and transparent threshold callouts on the scrip's
own features supply the human-readable "why". Every rendered reason describes the message or
the scrip's market behaviour — never a buy/sell/hold/avoid call (CLAUDE.md rule 1).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import joblib
import pandas as pd
from pydantic import BaseModel

from niveshak.parse.tip import Tip
from niveshak.score.dataset import FEATURE_COLUMNS, LIQUIDITY_ORDER
from niveshak.score.redflags import score_red_flags

# Documented blend + bands (docs/DECISIONS.md D1).
MODEL_WEIGHT = 0.6
REDFLAG_WEIGHT = 0.4
BAND_ELEVATED_MIN = 25   # [0,25) low, [25,60) elevated, [60,100] high
BAND_HIGH_MIN = 60

Band = Literal["low", "elevated", "high"]

DISCLAIMER = (
    "Manipulation-risk assessment of a message, not investment advice. "
    "Not a view on the security."
)


class Contribution(BaseModel):
    code: str
    reason: str            # describes the message or the scrip's behaviour — never advice
    impact: float          # points (out of 100) this driver adds to the final score
    half: Literal["message", "market"]


class RiskScore(BaseModel):
    value: int                       # 0-100
    band: Band
    confidence: float                # 0-1
    ticker: str | None
    model_susceptibility: float      # 0-1 calibrated pump-then-dump probability
    message_red_flag_score: float    # 0-1
    contributions: list[Contribution]  # top drivers, impact-desc
    notes: list[str] = []
    disclaimer: str = DISCLAIMER


def band_for(value: int) -> Band:
    if value >= BAND_HIGH_MIN:
        return "high"
    if value >= BAND_ELEVATED_MIN:
        return "elevated"
    return "low"


def _scrip_factors(feat: dict[str, Any]) -> list[str]:
    """Transparent, behavioural callouts explaining the market half (no advice, no SHAP)."""
    out: list[str] = []
    ru = feat.get("runup_20d")
    if ru is not None and ru >= 0.5:
        out.append("already up sharply over the past month")
    uc = feat.get("upper_circuit_count_10d")
    if uc is not None and uc >= 3:
        out.append("repeated upper-circuit closes recently")
    vz = feat.get("volume_zscore_60d")
    if vz is not None and vz >= 3:
        out.append("unusual recent volume spike")
    if str(feat.get("liquidity_bucket")) == "micro":
        out.append("thin, microcap-level liquidity")
    if bool(feat.get("is_sme")):
        out.append("SME-segment scrip")
    dsl = feat.get("days_since_listing")
    if dsl is not None and dsl < 90:
        out.append("listed recently")
    return out


def build_risk_score(
    tip: Tip, model_susceptibility: float, feature_row: dict[str, Any] | None,
) -> RiskScore:
    """Pure blend + banding + explanation. No DB or model access (unit-testable)."""
    prob = max(0.0, min(1.0, float(model_susceptibility)))
    rf = score_red_flags(tip)

    market_pts = MODEL_WEIGHT * prob * 100.0
    value = round(market_pts + REDFLAG_WEIGHT * rf.score * 100.0)
    value = max(0, min(100, value))

    contributions: list[Contribution] = [
        Contribution(code=c.code, reason=c.reason,
                     impact=round(c.weight * REDFLAG_WEIGHT * 100.0, 1), half="message")
        for c in rf.contributions
    ]
    if prob > 0 and feature_row is not None:
        factors = _scrip_factors(feature_row)
        reason = "Scrip's recent market behaviour resembles pump-prone setups"
        if factors:
            reason += " (" + "; ".join(factors[:2]) + ")"
        contributions.append(Contribution(
            code="market_susceptibility", reason=reason,
            impact=round(market_pts, 1), half="market"))

    top = sorted(contributions, key=lambda c: c.impact, reverse=True)[:3]

    notes: list[str] = []
    if tip.ticker is None:
        notes.append("Ticker could not be resolved — score reflects message signals only.")
        confidence = 0.5
    elif feature_row is None:
        notes.append("No recent market data for this scrip — score reflects message signals only.")
        confidence = 0.6
    else:
        confidence = 0.9

    return RiskScore(
        value=value, band=band_for(value), confidence=confidence, ticker=tip.ticker,
        model_susceptibility=round(prob, 4), message_red_flag_score=rf.score,
        contributions=top, notes=notes,
    )


class Scorer:
    """Holds the DB connection, model artifact, and resolver; scores text or Tips."""

    def __init__(self, con: Any, model: Any, resolver: Any) -> None:
        self.con = con
        self.model = model
        self.resolver = resolver

    @classmethod
    def from_paths(cls, db_path: str | Path | None = None,
                   models_dir: str | Path = "models") -> Scorer:
        from niveshak.market import db
        from niveshak.parse.tickers import TickerResolver
        con = db.connect(db_path)
        model = load_latest_model(models_dir)
        resolver = TickerResolver.from_duckdb(con)
        return cls(con, model, resolver)

    def _susceptibility(self, ticker: str | None) -> tuple[float, dict[str, Any] | None]:
        if ticker is None or self.model is None:
            return 0.0, None
        row = self.con.execute(
            f"SELECT {', '.join(FEATURE_COLUMNS)} FROM market_features "
            "WHERE symbol = ? ORDER BY trade_date DESC LIMIT 1", [ticker],
        ).fetch_df()
        if row.empty:
            return 0.0, None
        feat = row.iloc[0].to_dict()
        X = row.copy()
        X["is_sme"] = X["is_sme"].astype(int)
        X["liquidity_bucket"] = X["liquidity_bucket"].map(LIQUIDITY_ORDER).astype(float)
        prob = float(self.model.predict_proba(X[self.model.feature_names])[0])
        return prob, feat

    def score_tip(self, tip: Tip) -> RiskScore:
        prob, feat = self._susceptibility(tip.ticker)
        return build_risk_score(tip, prob, feat)

    def score_text(self, text: str, *, source: str = "manual") -> RiskScore:
        from niveshak.parse import parser as P
        tip = P.parse_message(text, source=source, resolver=self.resolver)  # type: ignore[arg-type]
        return self.score_tip(tip)


def load_latest_model(models_dir: str | Path = "models") -> Any:
    """Load the newest saved model via models/latest.txt, or None if none exists."""
    models_dir = Path(models_dir)
    pointer = models_dir / "latest.txt"
    if not pointer.exists():
        return None
    return joblib.load(models_dir / pointer.read_text().strip())
