"""Coordination burst detection (SPEC §3.5, the demo differentiator).

The signal: how many *distinct channels* are pushing a ticker inside a short window (48h),
relative to that ticker's own baseline. A microcap that normally gets one stray mention a
week suddenly appearing across five channels in two days is the fingerprint of a coordinated
pump — independent of what any single message says.

We deliberately keep only burst detection (Louvain community attribution is cut, see
BUILD_PLAN). Everything here is pure over a mentions DataFrame so it is unit-testable; the
DB-backed `BurstProvider` is a thin wrapper.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

# Defaults — documented, tunable.
WINDOW_HOURS = 48
BASELINE_DAYS = 90
STEP_HOURS = 24
MIN_CHANNELS = 3          # a "burst" needs at least this many distinct channels...
Z_THRESHOLD = 2.0         # ...and this many std-devs above the ticker's own baseline

MENTION_COLUMNS = ("channel_id", "ticker", "posted_at")


@dataclass(frozen=True)
class BurstStat:
    ticker: str
    n_channels: int          # distinct channels in the current 48h window
    baseline_mean: float
    baseline_std: float
    z: float                 # (n_channels - mean) / std

    @property
    def is_burst(self) -> bool:
        return self.n_channels >= MIN_CHANNELS and self.z >= Z_THRESHOLD


def _distinct_channels(df: pd.DataFrame, start: datetime, end: datetime) -> int:
    m = df[(df["posted_at"] > start) & (df["posted_at"] <= end)]
    return int(m["channel_id"].nunique())


def burst_stats(
    mentions: pd.DataFrame, ticker: str, as_of: datetime, *,
    window_hours: int = WINDOW_HOURS, baseline_days: int = BASELINE_DAYS,
    step_hours: int = STEP_HOURS,
) -> BurstStat:
    """Distinct-channel count for `ticker` in the current window vs its trailing baseline."""
    df = mentions[mentions["ticker"] == ticker]
    win = timedelta(hours=window_hours)
    current = _distinct_channels(df, as_of - win, as_of)

    samples: list[int] = []
    t = as_of - timedelta(days=baseline_days)
    while t < as_of - win:                       # exclude the current window from the baseline
        samples.append(_distinct_channels(df, t - win, t))
        t += timedelta(hours=step_hours)

    mean = float(np.mean(samples)) if samples else 0.0
    std = float(np.std(samples)) if samples else 0.0
    if std > 1e-9:
        z = (current - mean) / std
    else:
        z = float("inf") if current > mean else 0.0
    return BurstStat(ticker, current, mean, std, z)


def watchlist(
    mentions: pd.DataFrame, as_of: datetime | None = None, *, limit: int = 25,
    **kw: int,
) -> list[BurstStat]:
    """Tickers currently in a burst, ranked most-anomalous first (for the Pump Watchlist)."""
    if mentions.empty:
        return []
    as_of = as_of or mentions["posted_at"].max()
    win = timedelta(hours=kw.get("window_hours", WINDOW_HOURS))
    active = mentions[(mentions["posted_at"] > as_of - win) & (mentions["posted_at"] <= as_of)]
    stats = [burst_stats(mentions, t, as_of, **kw) for t in active["ticker"].dropna().unique()]
    bursts = [s for s in stats if s.is_burst]
    bursts.sort(key=lambda s: (s.z if np.isfinite(s.z) else 1e9, s.n_channels), reverse=True)
    return bursts[:limit]


class BurstProvider:
    """DB-backed burst lookups over the `channel_mentions` table. Safe if the table is empty."""

    def __init__(self, con: object) -> None:
        self.con = con

    def _mentions(self) -> pd.DataFrame:
        try:
            df = self.con.execute(  # type: ignore[attr-defined]
                "SELECT channel_id, ticker, posted_at FROM channel_mentions "
                "WHERE ticker IS NOT NULL"
            ).fetch_df()
        except Exception:  # noqa: BLE001 - table may not exist on a bare box
            return pd.DataFrame(columns=list(MENTION_COLUMNS))
        if not df.empty:
            df["posted_at"] = pd.to_datetime(df["posted_at"])
        return df

    def for_ticker(self, ticker: str | None, as_of: datetime | None = None) -> BurstStat | None:
        if not ticker:
            return None
        df = self._mentions()
        if df.empty or (df["ticker"] == ticker).sum() == 0:
            return None
        return burst_stats(df, ticker, as_of or df["posted_at"].max())

    def watchlist(self, limit: int = 25) -> list[BurstStat]:
        return watchlist(self._mentions(), limit=limit)
