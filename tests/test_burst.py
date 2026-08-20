"""Tests for coordination burst detection on synthetic channel-mention data."""

from datetime import datetime, timedelta

import pandas as pd

from niveshak.graph import burst as B

AS_OF = datetime(2026, 8, 19, 12, 0)


def _mentions() -> pd.DataFrame:
    rows = []
    # PUMPCO: almost nothing in the baseline, then 5 distinct channels in the last day.
    rows.append(("c1", "PUMPCO", AS_OF - timedelta(days=70)))
    rows.append(("c2", "PUMPCO", AS_OF - timedelta(days=45)))
    for i, c in enumerate(["c1", "c2", "c3", "c4", "c5"]):
        rows.append((c, "PUMPCO", AS_OF - timedelta(hours=6 + i)))
    # STEADYCO: the same two channels mention it steadily, incl. recently (n<MIN_CHANNELS).
    d = 88
    while d > 0:
        rows.append(("c1", "STEADYCO", AS_OF - timedelta(days=d)))
        rows.append(("c2", "STEADYCO", AS_OF - timedelta(days=d, hours=1)))
        d -= 2
    df = pd.DataFrame(rows, columns=["channel_id", "ticker", "posted_at"])
    df["posted_at"] = pd.to_datetime(df["posted_at"])
    return df


def test_pump_is_a_burst():
    s = B.burst_stats(_mentions(), "PUMPCO", AS_OF)
    assert s.n_channels == 5
    assert s.z >= B.Z_THRESHOLD
    assert s.is_burst


def test_steady_is_not_a_burst():
    s = B.burst_stats(_mentions(), "STEADYCO", AS_OF)
    assert s.n_channels < B.MIN_CHANNELS      # only 2 channels -> never a burst
    assert not s.is_burst


def test_watchlist_surfaces_only_bursts():
    wl = B.watchlist(_mentions(), AS_OF)
    tickers = [s.ticker for s in wl]
    assert "PUMPCO" in tickers
    assert "STEADYCO" not in tickers


def test_empty_mentions_is_safe():
    assert B.watchlist(pd.DataFrame(columns=["channel_id", "ticker", "posted_at"])) == []


def test_provider_returns_none_without_data():
    class _Con:
        def execute(self, *a, **k):
            raise RuntimeError("no such table")
    assert B.BurstProvider(_Con()).for_ticker("PUMPCO") is None
    assert B.BurstProvider(_Con()).for_ticker(None) is None
