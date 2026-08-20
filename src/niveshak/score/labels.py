"""Weak outcome-rule labeller — the pump-then-dump pattern (SPEC §3.6).

A tip about a scrip on date D is weakly POSITIVE if, from D:
  1. the close rises >= +25% above close_D at some session within the next 30 sessions
     (the run-up), and
  2. from that run-up peak, the close then falls >= -30% below the peak within the next 30
     sessions (the collapse).

**This uses forward returns. It is a TRAINING LABEL ONLY and must never be a model feature.**
That is not a style rule — a forward-looking column in the feature matrix is a guaranteed
leak that inflates every metric. `LABEL_COLUMN` and `FORBIDDEN_FEATURE_COLUMNS` below are
enforced with an assertion (`assert_no_label_leakage`) that the dataset builder calls before
training, so the rule is checked in code, not just trusted in comments.

Leakage-free labelling also means we never guess a label we can't observe: if there isn't
enough future data to *rule out* the pattern, the label is NaN (undefined) and the row is
dropped from training — it is never silently called negative.
"""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pandas as pd

# Documented thresholds. Tunable hyperparameters, not constants of nature (SPEC §3.6).
RUNUP_THRESHOLD = 0.25      # +25% from close_D defines the run-up
DRAWDOWN_THRESHOLD = 0.30   # -30% from the run-up peak defines the collapse
RUNUP_WINDOW = 30           # sessions to reach the run-up
DRAWDOWN_WINDOW = 30        # sessions after the peak to reach the collapse

LABEL_COLUMN = "y_pump_dump"

# Columns that are forward-looking or are the label itself. None of these may ever appear
# in the model's feature list. Enforced by assert_no_label_leakage().
FORBIDDEN_FEATURE_COLUMNS = frozenset({
    LABEL_COLUMN, "label", "y", "target", "outcome",
    "fwd_return", "forward_return", "future_return", "peak_return",
})


def label_from_closes(close: np.ndarray) -> np.ndarray:
    """Label every position in an ascending close-price array. Returns {1.0, 0.0, NaN}.

    NaN means undefined: the required forward window isn't fully observable yet and the
    pattern hasn't already been confirmed, so we refuse to assign a label.
    """
    close = np.asarray(close, dtype=float)
    n = close.size
    out = np.full(n, np.nan, dtype=float)

    for i in range(n):
        c0 = close[i]
        if not np.isfinite(c0) or c0 <= 0:
            continue

        w1 = close[i + 1 : i + 1 + RUNUP_WINDOW]           # run-up window
        if w1.size == 0:
            continue
        peak_rel = i + 1 + int(np.nanargmax(w1))           # absolute index of the peak
        peak_val = close[peak_rel]

        runup_hit = np.isfinite(peak_val) and peak_val >= c0 * (1.0 + RUNUP_THRESHOLD)
        if not runup_hit:
            # Only a definitive NEGATIVE if we actually saw the full run-up window.
            out[i] = 0.0 if w1.size == RUNUP_WINDOW else np.nan
            continue

        w2 = close[peak_rel + 1 : peak_rel + 1 + DRAWDOWN_WINDOW]   # collapse window
        collapse_level = peak_val * (1.0 - DRAWDOWN_THRESHOLD)
        if w2.size and np.nanmin(w2) <= collapse_level:
            out[i] = 1.0                                   # run-up + collapse confirmed
        elif w2.size == DRAWDOWN_WINDOW:
            out[i] = 0.0                                   # full window, no collapse
        else:
            out[i] = np.nan                                # not enough future data yet
    return out


def label_symbol_history(df: pd.DataFrame, *, close_col: str = "close") -> pd.Series:
    """Label one symbol's history (must be sorted ascending by trade_date)."""
    return pd.Series(label_from_closes(df[close_col].to_numpy()), index=df.index,
                     name=LABEL_COLUMN)


def assert_no_label_leakage(feature_names: Iterable[str], *, label_col: str = LABEL_COLUMN) -> None:
    """Raise if the label or any forward-looking column is in the feature list.

    Called by the dataset builder before every fit. This is the code-level enforcement of
    "the outcome rule must never be a feature".
    """
    feats = list(feature_names)
    if label_col in feats:
        raise AssertionError(
            f"LEAKAGE: label column {label_col!r} is in the feature list {feats}"
        )
    banned = FORBIDDEN_FEATURE_COLUMNS.intersection(feats)
    if banned:
        raise AssertionError(
            f"LEAKAGE: forward-looking column(s) {sorted(banned)} are in the feature list"
        )
