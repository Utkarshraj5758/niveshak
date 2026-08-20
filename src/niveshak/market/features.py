"""Per-(symbol, series, date) market features for scrip-susceptibility scoring (SPEC §3.3).

Design rules that make these safe to trust on demo day:

* **One pure function per feature.** Each takes a single symbol's price history as a
  DataFrame sorted ascending by ``trade_date`` and returns a pandas Series aligned to that
  frame (the feature's value AT each date). This is what makes every feature unit-testable
  with a hand-built series — the mandate for Day 1 afternoon.
* **Strictly backward-looking.** A feature at date D uses only rows up to and including D.
  Rolling baselines that describe "normality" (volume z-score, delivery trend) use the
  prior sessions via ``.shift(1)`` so today isn't compared against itself. Nothing here may
  ever see the future — the forward outcome rule is a training label, never a feature.
* **Every row keeps ``is_sme``.** SME scrips have different circuit rules and thinner data;
  a model that forgets the flag overfits to mainboard (see CLAUDE.md).

Two honest substitutions, documented where they occur:
* ``upper_circuit_count_10d`` uses a *locked-price* proxy — bhavcopy carries no circuit band.
* ``liquidity_bucket`` buckets trailing median turnover, standing in for the "market-cap
  bucket" slot: bhavcopy has no shares-outstanding, and illiquidity is the feature that
  actually drives pump susceptibility. True free-float market cap is a Phase-2 data source.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

try:  # duckdb is only needed by the store builder, not by the pure feature functions
    import duckdb
except ImportError:  # pragma: no cover
    duckdb = None  # type: ignore[assignment]

# Columns a per-symbol history frame must provide (sorted ascending by trade_date).
REQUIRED_COLS = (
    "trade_date", "close", "high", "low", "prev_close",
    "total_traded_qty", "turnover_lacs", "deliv_pct",
)

# Daily-turnover thresholds (in lakh INR: 100 lakh = 1 crore) for the size proxy.
_LIQUIDITY_EDGES = (100.0, 1000.0, 10000.0)          # <1cr, 1-10cr, 10-100cr, >=100cr
_LIQUIDITY_LABELS = ("micro", "small", "mid", "large")


# --- price run-up -----------------------------------------------------------------

def trailing_return(close: pd.Series, window: int) -> pd.Series:
    """Fractional return of ``close`` over the trailing ``window`` sessions (NaN early)."""
    prior = close.shift(window)
    return close / prior.where(prior != 0.0) - 1.0


def runup_5d(df: pd.DataFrame) -> pd.Series:
    """5-session price run-up into each date."""
    return trailing_return(df["close"].astype(float), 5)


def runup_10d(df: pd.DataFrame) -> pd.Series:
    """10-session price run-up into each date."""
    return trailing_return(df["close"].astype(float), 10)


def runup_20d(df: pd.DataFrame) -> pd.Series:
    """20-session price run-up into each date."""
    return trailing_return(df["close"].astype(float), 20)


# --- volume anomaly ---------------------------------------------------------------

def volume_zscore_60d(df: pd.DataFrame, *, min_periods: int = 20) -> pd.Series:
    """z-score of today's volume vs the trailing 60-session baseline (excluding today)."""
    vol = df["total_traded_qty"].astype(float)
    base = vol.shift(1)
    mean = base.rolling(60, min_periods=min_periods).mean()
    std = base.rolling(60, min_periods=min_periods).std()
    return (vol - mean) / std.where(std > 0.0)


# --- delivery -------------------------------------------------------------------

def delivery_pct(df: pd.DataFrame) -> pd.Series:
    """Today's delivery percentage (pass-through of the bhavcopy column)."""
    return df["deliv_pct"].astype(float)


def delivery_pct_trend_10d(df: pd.DataFrame, *, min_periods: int = 3) -> pd.Series:
    """Today's delivery % minus its mean over the prior 10 sessions (points, not ratio)."""
    d = df["deliv_pct"].astype(float)
    base = d.shift(1).rolling(10, min_periods=min_periods).mean()
    return d - base


# --- upper-circuit proxy --------------------------------------------------------

def is_upper_circuit_like(df: pd.DataFrame) -> pd.Series:
    """Boolean: session looks locked at the upper limit.

    Proxy (bhavcopy has no circuit band): the whole session traded at one price
    (``high == low``) and closed above the previous close. When a scrip is locked up all
    day, every trade prints at the ceiling, so high == low == close > prev_close.
    """
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    prev = df["prev_close"].astype(float)
    locked = (high == low) & high.notna()
    return (locked & (close > prev)).fillna(False)


def upper_circuit_count_10d(df: pd.DataFrame) -> pd.Series:
    """Count of upper-circuit-like sessions in the trailing 10 sessions (inclusive)."""
    uc = is_upper_circuit_like(df).astype(int)
    return uc.rolling(10, min_periods=1).sum()


# --- size / liquidity proxy ------------------------------------------------------

def trailing_median_turnover_20d(df: pd.DataFrame, *, min_periods: int = 5) -> pd.Series:
    """Median daily turnover (lakh INR) over the trailing 20 sessions (inclusive)."""
    return df["turnover_lacs"].astype(float).rolling(20, min_periods=min_periods).median()


def liquidity_bucket(df: pd.DataFrame) -> pd.Series:
    """Categorical size proxy from trailing median turnover: micro/small/mid/large.

    Stands in for the market-cap bucket (no shares-outstanding in bhavcopy). Returns the
    pandas 'object' dtype with NaN until enough history exists.
    """
    med = trailing_median_turnover_20d(df)
    idx = np.digitize(med.to_numpy(dtype=float), _LIQUIDITY_EDGES, right=False)
    labels = np.array(_LIQUIDITY_LABELS, dtype=object)[idx]
    out = pd.Series(labels, index=df.index, dtype=object)
    return out.where(med.notna())


# --- listing age ----------------------------------------------------------------

def days_since_listing(df: pd.DataFrame, listing_date: object) -> pd.Series:
    """Calendar days from listing to each trade_date. NaN if listing date is unknown."""
    td = pd.to_datetime(df["trade_date"])
    if listing_date is None or pd.isna(listing_date):
        return pd.Series(np.nan, index=df.index, dtype=float)
    delta = (td - pd.Timestamp(listing_date)).dt.days
    return delta.astype("float")


# --- assembly -------------------------------------------------------------------

FEATURE_COLUMNS = (
    "runup_5d", "runup_10d", "runup_20d", "volume_zscore_60d", "delivery_pct",
    "delivery_pct_trend_10d", "upper_circuit_count_10d", "trailing_median_turnover_20d",
    "liquidity_bucket", "days_since_listing", "is_sme",
)


def compute_symbol_features(
    df: pd.DataFrame, *, listing_date: object = None, is_sme: bool = False
) -> pd.DataFrame:
    """Apply every feature to one symbol's sorted history. Returns keys + feature columns.

    ``df`` must be sorted ascending by ``trade_date`` and contain ``REQUIRED_COLS`` plus
    ``symbol``/``series``/``exchange`` keys.
    """
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"history missing columns {missing}")
    df = df.sort_values("trade_date").reset_index(drop=True)

    out = pd.DataFrame({
        "exchange": df.get("exchange", "NSE"),
        "symbol": df["symbol"] if "symbol" in df else pd.NA,
        "series": df["series"] if "series" in df else pd.NA,
        "trade_date": df["trade_date"],
        "runup_5d": runup_5d(df),
        "runup_10d": runup_10d(df),
        "runup_20d": runup_20d(df),
        "volume_zscore_60d": volume_zscore_60d(df),
        "delivery_pct": delivery_pct(df),
        "delivery_pct_trend_10d": delivery_pct_trend_10d(df),
        "upper_circuit_count_10d": upper_circuit_count_10d(df).astype("Int64"),
        "trailing_median_turnover_20d": trailing_median_turnover_20d(df),
        "liquidity_bucket": liquidity_bucket(df),
        "days_since_listing": days_since_listing(df, listing_date),
        "is_sme": bool(is_sme),
    })
    return out


# --- DuckDB feature store --------------------------------------------------------

MARKET_FEATURES_SCHEMA = """
CREATE TABLE IF NOT EXISTS market_features (
    exchange                     VARCHAR NOT NULL,
    symbol                       VARCHAR NOT NULL,
    series                       VARCHAR NOT NULL,
    trade_date                   DATE    NOT NULL,
    runup_5d                     DOUBLE,
    runup_10d                    DOUBLE,
    runup_20d                    DOUBLE,
    volume_zscore_60d            DOUBLE,
    delivery_pct                 DOUBLE,
    delivery_pct_trend_10d       DOUBLE,
    upper_circuit_count_10d      BIGINT,
    trailing_median_turnover_20d DOUBLE,
    liquidity_bucket             VARCHAR,
    days_since_listing           DOUBLE,
    is_sme                       BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (exchange, symbol, series, trade_date)
);
"""


def build_feature_store(con: "duckdb.DuckDBPyConnection", *, min_history: int = 21) -> int:
    """Compute features for every (exchange, symbol, series) and load ``market_features``.

    Pulls the full price history joined to each symbol's listing date and SME flag, applies
    the per-symbol functions groupwise, and INSERT OR REPLACEs the result. Idempotent.
    Returns rows written. Groups shorter than ``min_history`` sessions are skipped (their
    windowed features would be entirely NaN).
    """
    if duckdb is None:  # pragma: no cover
        raise RuntimeError("duckdb not available")
    con.execute(MARKET_FEATURES_SCHEMA)

    prices = con.execute("""
        SELECT p.exchange, p.symbol, p.series, p.trade_date, p.close, p.high, p.low,
               p.prev_close, p.total_traded_qty, p.turnover_lacs, p.deliv_pct, p.is_sme,
               s.date_of_listing
        FROM daily_prices p
        LEFT JOIN symbols s
          ON s.exchange = p.exchange AND s.symbol = p.symbol AND s.series = p.series
        ORDER BY p.exchange, p.symbol, p.series, p.trade_date
    """).fetch_df()

    frames: list[pd.DataFrame] = []
    for (exch, sym, series), g in prices.groupby(["exchange", "symbol", "series"], sort=False):
        if len(g) < min_history:
            continue
        listing = g["date_of_listing"].iloc[0]
        is_sme = bool(g["is_sme"].iloc[0])
        feats = compute_symbol_features(g, listing_date=listing, is_sme=is_sme)
        frames.append(feats)

    if not frames:
        return 0
    out = pd.concat(frames, ignore_index=True)
    con.register("_feat_df", out)
    con.execute("INSERT OR REPLACE INTO market_features SELECT * FROM _feat_df")
    con.unregister("_feat_df")
    return len(out)
