"""Tests for the outcome-rule labeller and the leakage assertion.

The label defines the entire training signal, so each branch is pinned: confirmed positive,
the two kinds of negative, and the "undefined -> NaN, never silently negative" guard. The
leakage assertion is tested because it is the code-level enforcement the brief demands.
"""

import numpy as np
import pytest

from niveshak.score import labels as L


def test_positive_runup_then_collapse():
    # +35% run-up (peak at idx 5), then falls below 0.7*peak by idx 9.
    close = np.array([100, 105, 110, 120, 130, 135, 130, 120, 100, 88] + [88] * 30, dtype=float)
    y = L.label_from_closes(close)
    assert y[0] == 1.0


def test_negative_no_runup():
    close = np.full(40, 100.0)                       # never rises 25%
    y = L.label_from_closes(close)
    assert y[0] == 0.0                               # full window observed -> definite negative


def test_negative_runup_without_collapse():
    # +30% run-up at idx 1, then holds near the top for a full drawdown window.
    close = np.array([100, 130] + [128] * 33, dtype=float)
    y = L.label_from_closes(close)
    assert y[0] == 0.0


def test_undefined_when_future_incomplete():
    close = np.array([100, 101, 102], dtype=float)   # window nowhere near complete
    y = L.label_from_closes(close)
    assert np.isnan(y[0])


def test_undefined_after_runup_but_collapse_window_incomplete():
    # Run-up confirmed, but only a few sessions after the peak and no collapse yet -> NaN.
    close = np.array([100, 130, 129, 128], dtype=float)
    y = L.label_from_closes(close)
    assert np.isnan(y[0])


def test_nonpositive_price_is_undefined():
    close = np.array([0.0, 100.0, 130.0] + [90.0] * 30, dtype=float)
    y = L.label_from_closes(close)
    assert np.isnan(y[0])


def test_assert_no_label_leakage_passes_clean_features():
    L.assert_no_label_leakage(["runup_5d", "volume_zscore_60d", "is_sme"])


def test_assert_no_label_leakage_catches_label():
    with pytest.raises(AssertionError, match="LEAKAGE"):
        L.assert_no_label_leakage(["runup_5d", L.LABEL_COLUMN])


def test_assert_no_label_leakage_catches_forward_column():
    with pytest.raises(AssertionError, match="LEAKAGE"):
        L.assert_no_label_leakage(["runup_5d", "forward_return"])
