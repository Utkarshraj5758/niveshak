"""One test per market feature (SPEC §3.3), on hand-built series with known answers.

A silently wrong feature is unrecoverable on this timeline, so every function is pinned
here against values computed by hand, plus the leakage guard that features never read the
future.
"""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from niveshak.market import features as F


def _history(n: int = 30, **overrides) -> pd.DataFrame:
    """A clean ascending history; override any column with a full-length sequence."""
    close = np.arange(100, 100 + n, dtype=float)
    df = pd.DataFrame({
        "exchange": "NSE",
        "symbol": "TEST",
        "series": "EQ",
        "trade_date": pd.bdate_range("2025-01-01", periods=n).date,
        "close": close,
        "high": close,
        "low": close - 1.0,
        "prev_close": np.concatenate([[np.nan], close[:-1]]),
        "total_traded_qty": np.full(n, 1000.0),
        "turnover_lacs": np.full(n, 500.0),
        "deliv_pct": np.full(n, 40.0),
    })
    for k, v in overrides.items():
        df[k] = v
    return df


def test_runup_5d():
    df = _history()
    r = F.runup_5d(df)
    assert np.isnan(r.iloc[4])                       # not enough history yet
    # close[10]=110, close[5]=105 -> 110/105 - 1
    assert r.iloc[10] == pytest.approx(110 / 105 - 1)


def test_runup_10d():
    df = _history()
    assert F.runup_10d(df).iloc[20] == pytest.approx(120 / 110 - 1)


def test_runup_20d():
    df = _history()
    assert F.runup_20d(df).iloc[25] == pytest.approx(125 / 105 - 1)


def test_volume_zscore_60d_flags_a_spike():
    n = 40
    rng = np.random.default_rng(0)
    vol = 1000.0 + rng.normal(0, 50, n)              # baseline with real variance
    vol[-1] = 8000.0                                 # today spikes hard
    df = _history(n, total_traded_qty=vol)
    z = F.volume_zscore_60d(df, min_periods=10)
    assert z.iloc[-1] > 5                            # clearly anomalous
    assert np.isnan(z.iloc[0])                       # no baseline at the start


def test_volume_zscore_60d_flat_baseline_is_nan_not_inf():
    df = _history(40, total_traded_qty=np.full(40, 1000.0))  # zero-variance baseline
    z = F.volume_zscore_60d(df, min_periods=10)
    assert np.isnan(z.iloc[-1])                      # undefined, never +inf


def test_delivery_pct_passthrough():
    df = _history(deliv_pct=np.linspace(10, 39, 30))
    assert F.delivery_pct(df).iloc[-1] == pytest.approx(39.0)


def test_delivery_pct_trend_10d():
    d = np.full(30, 30.0)
    d[-1] = 55.0                                     # jump above the 30% norm
    df = _history(deliv_pct=d)
    assert F.delivery_pct_trend_10d(df).iloc[-1] == pytest.approx(25.0)


def test_is_upper_circuit_like():
    n = 5
    close = np.array([100, 105, 110, 110, 90], dtype=float)
    high = np.array([100, 105, 110, 112, 90], dtype=float)   # day 3 locked, day 4 has range
    low = np.array([100, 105, 110, 108, 90], dtype=float)
    prev = np.array([np.nan, 100, 105, 110, 110], dtype=float)
    df = pd.DataFrame({
        "high": high, "low": low, "close": close, "prev_close": prev,
    })
    uc = F.is_upper_circuit_like(df)
    assert list(uc) == [False, True, True, False, False]     # locked & up on days 1,2


def test_upper_circuit_count_10d():
    n = 12
    # every session locked-up: high==low, close>prev
    close = np.arange(100, 100 + n, dtype=float)
    df = pd.DataFrame({
        "high": close, "low": close, "close": close,
        "prev_close": np.concatenate([[99.0], close[:-1]]),
    })
    cnt = F.upper_circuit_count_10d(df)
    assert cnt.iloc[-1] == 10                        # capped by the 10-session window
    assert cnt.iloc[0] == 1


def test_trailing_median_turnover_20d():
    df = _history(turnover_lacs=np.full(30, 750.0))
    assert F.trailing_median_turnover_20d(df).iloc[-1] == pytest.approx(750.0)


def test_liquidity_bucket_boundaries():
    turn = np.array([50.0, 500.0, 5000.0, 50000.0] + [50000.0] * 26)
    df = _history(turnover_lacs=turn)
    # trailing median at the last row is dominated by 50000 -> 'large'
    b = F.liquidity_bucket(df)
    assert b.iloc[-1] == "large"
    # a purely micro history
    dfm = _history(turnover_lacs=np.full(30, 20.0))
    assert F.liquidity_bucket(dfm).iloc[-1] == "micro"


def test_days_since_listing():
    df = _history()
    dsl = F.days_since_listing(df, date(2024, 12, 2))
    assert dsl.iloc[0] == (pd.Timestamp(df["trade_date"].iloc[0]) - pd.Timestamp("2024-12-02")).days
    assert np.isnan(F.days_since_listing(df, None).iloc[0])


def test_no_lookahead_leakage():
    """Truncating the future must not change any past feature value."""
    df = _history(40)
    full = F.compute_symbol_features(df, listing_date=date(2024, 1, 1))
    truncated = F.compute_symbol_features(df.iloc[:30].copy(), listing_date=date(2024, 1, 1))
    cols = ["runup_5d", "runup_10d", "runup_20d", "volume_zscore_60d",
            "delivery_pct_trend_10d", "upper_circuit_count_10d"]
    pd.testing.assert_frame_equal(
        full.loc[:29, cols].reset_index(drop=True),
        truncated.loc[:29, cols].reset_index(drop=True),
        check_dtype=False,
    )


def test_compute_symbol_features_shape_and_keys():
    df = _history(40)
    out = F.compute_symbol_features(df, listing_date=date(2024, 1, 1), is_sme=True)
    assert len(out) == 40
    assert bool(out["is_sme"].iloc[0]) is True
    for c in F.FEATURE_COLUMNS:
        assert c in out.columns


def test_compute_rejects_missing_columns():
    with pytest.raises(ValueError):
        F.compute_symbol_features(pd.DataFrame({"trade_date": [], "close": []}))
