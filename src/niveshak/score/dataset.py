"""Assemble the labelled training dataset and split it in time (never at random).

Pipeline:
  daily_prices --(forward outcome rule)--> labels
  market_features --(join on keys)--> feature matrix
  drop undefined labels -> temporal split with an embargo gap -> (train, calib, test)

The embargo matters: the label at date D is computed from up to ~60 forward sessions, so a
training row within one label-horizon of the test boundary would "see" test-period outcomes.
We drop those rows (embargo) so no forward-label window straddles the split.

`assert_no_label_leakage(FEATURE_COLUMNS)` runs at import-adjacent build time so a
forward-looking column can never silently reach the model.
"""

from __future__ import annotations

from dataclasses import dataclass

import duckdb
import pandas as pd

from niveshak.score import labels as L

# The model's inputs. Every one is backward-looking (see market/features.py). The label and
# any forward column are excluded by construction and enforced below.
FEATURE_COLUMNS: list[str] = [
    "runup_5d",
    "runup_10d",
    "runup_20d",
    "volume_zscore_60d",
    "delivery_pct",
    "delivery_pct_trend_10d",
    "upper_circuit_count_10d",
    "trailing_median_turnover_20d",
    "days_since_listing",
    "is_sme",
    "liquidity_bucket",
]
# liquidity_bucket is ordinal (micro < small < mid < large), so we encode it as an ordered
# integer rather than one-hot: the order is real information and it keeps the model input
# purely numeric (no categorical special-casing needed).
LIQUIDITY_ORDER: dict[str, int] = {"micro": 0, "small": 1, "mid": 2, "large": 3}
CATEGORICAL_COLUMNS: list[str] = []
KEY_COLUMNS: list[str] = ["exchange", "symbol", "series", "trade_date"]

# ~60 trading sessions of forward label window ~= 90 calendar days; pad a little.
DEFAULT_EMBARGO_DAYS = 95


@dataclass
class Split:
    train: pd.DataFrame
    calib: pd.DataFrame
    test: pd.DataFrame
    test_start: pd.Timestamp
    calib_start: pd.Timestamp
    embargo_days: int


def compute_labels(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Compute the forward outcome-rule label for every (exchange, symbol, series, date)."""
    prices = con.execute("""
        SELECT exchange, symbol, series, trade_date, close
        FROM daily_prices
        ORDER BY exchange, symbol, series, trade_date
    """).fetch_df()
    parts: list[pd.DataFrame] = []
    for _, g in prices.groupby(["exchange", "symbol", "series"], sort=False):
        g = g.copy()
        g[L.LABEL_COLUMN] = L.label_symbol_history(g).to_numpy()
        parts.append(g[KEY_COLUMNS + [L.LABEL_COLUMN]])
    return pd.concat(parts, ignore_index=True)


def build_labeled_dataset(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Join market_features to labels, keep only rows with a defined label."""
    assert_feature_list_clean()
    feats = con.execute(f"""
        SELECT {", ".join(KEY_COLUMNS + FEATURE_COLUMNS)}
        FROM market_features
    """).fetch_df()
    labels_df = compute_labels(con)
    df = feats.merge(labels_df, on=KEY_COLUMNS, how="inner")
    df = df.dropna(subset=[L.LABEL_COLUMN]).reset_index(drop=True)
    df[L.LABEL_COLUMN] = df[L.LABEL_COLUMN].astype(int)
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df["is_sme"] = df["is_sme"].astype(int)
    # ordinal-encode liquidity to a float code, preserving NaN (unknown history).
    df["liquidity_bucket"] = df["liquidity_bucket"].map(LIQUIDITY_ORDER).astype(float)
    return df


def assert_feature_list_clean() -> None:
    """Fail loudly if the feature list ever contains the label or a forward column."""
    L.assert_no_label_leakage(FEATURE_COLUMNS)


def temporal_split(
    df: pd.DataFrame, *, test_frac: float = 0.25, calib_frac: float = 0.20,
    embargo_days: int = DEFAULT_EMBARGO_DAYS,
) -> Split:
    """Split by time: earliest -> train, then calib, an embargo gap, then latest -> test.

    The only leakage-critical gap is train/calib -> test: with the embargo >= the forward
    label horizon, no training or calibration label window can reach into the test period,
    so the reported test PR-AUC is clean. Calibration is carved from the tail of the
    pre-test region (no second embargo, which would starve it on short spans).
    """
    dates = df["trade_date"]
    test_start = dates.quantile(1.0 - test_frac)
    embargo = pd.Timedelta(days=embargo_days)
    pre_cut = test_start - embargo                       # nothing in [pre_cut, test_start)

    test = df[dates >= test_start].copy()
    pre = df[dates < pre_cut]
    calib_start = pre["trade_date"].quantile(1.0 - calib_frac)
    calib = pre[pre["trade_date"] >= calib_start].copy()
    train = pre[pre["trade_date"] < calib_start].copy()
    return Split(train, calib, test, test_start, calib_start, embargo_days)
