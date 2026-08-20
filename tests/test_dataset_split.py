"""Tests for the temporal split — the guard against evaluating on the past you trained on."""

import numpy as np
import pandas as pd

from niveshak.score import dataset as D
from niveshak.score import labels as L


def _synthetic(n_days: int = 400) -> pd.DataFrame:
    dates = pd.bdate_range("2024-08-19", periods=n_days)
    rng = np.random.default_rng(0)
    rows = []
    for d in dates:
        for k in range(5):
            rows.append({
                "exchange": "NSE", "symbol": f"S{k}", "series": "EQ", "trade_date": d,
                **{c: rng.normal() for c in D.FEATURE_COLUMNS if c not in ("is_sme", "liquidity_bucket")},
                "is_sme": 0, "liquidity_bucket": "micro",
                L.LABEL_COLUMN: int(rng.random() < 0.1),
            })
    df = pd.DataFrame(rows)
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df["liquidity_bucket"] = df["liquidity_bucket"].astype("category")
    return df


def test_split_is_ordered_in_time_with_embargo():
    df = _synthetic()
    s = D.temporal_split(df, embargo_days=95)
    # train strictly before calib strictly before test
    assert s.train["trade_date"].max() < s.calib["trade_date"].min()
    assert s.calib["trade_date"].max() < s.test["trade_date"].min()
    # the leakage-critical embargo (calib -> test) is at least the label horizon
    assert (s.test_start - s.calib["trade_date"].max()) >= pd.Timedelta(days=95)


def test_split_covers_test_and_is_nonempty():
    df = _synthetic()
    s = D.temporal_split(df)
    assert len(s.train) > 0 and len(s.calib) > 0 and len(s.test) > 0
    # no test row leaks earlier than test_start
    assert s.test["trade_date"].min() >= s.test_start


def test_feature_list_has_no_leakage():
    D.assert_feature_list_clean()   # must not raise
