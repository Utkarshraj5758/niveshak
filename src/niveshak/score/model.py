"""Scrip-susceptibility model: histogram GBDT + isotonic calibration, saved with its manifest.

This is the 0.6-weight half of the final score. It is trained on market features alone,
weakly labelled by the forward outcome rule, on a temporal split. Probabilities are
calibrated with isotonic regression on a held-out (temporally earlier-than-test) slice so
the output is a meaningful probability, not just a ranking (calibration is never-cut).

Model choice: the brief specifies LightGBM, but LightGBM's native library segfaults on this
build machine (missing OpenMP/VC++ runtime). We use scikit-learn's
`HistGradientBoostingClassifier` instead — the same histogram-based GBDT family, pure within
scikit-learn, with native NaN handling. Documented in reports/model_v1.md.

The saved artifact carries the exact feature list it was trained on: a score produced by an
unknown feature set is a bug, not a fallback (CLAUDE.md).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.inspection import permutation_importance
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

from niveshak.score import labels as L
from niveshak.score.dataset import FEATURE_COLUMNS, Split


@dataclass
class Metrics:
    n_train: int
    n_calib: int
    n_test: int
    base_rate_test: float
    pr_auc_test: float
    roc_auc_test: float
    brier_calibrated_test: float
    lift_over_base: float
    calibration_bins: list[dict[str, float]] = field(default_factory=list)
    feature_importance_perm: dict[str, float] = field(default_factory=dict)


@dataclass
class TrainedModel:
    booster: HistGradientBoostingClassifier
    calibrator: IsotonicRegression
    feature_names: list[str]
    categorical_features: list[str]
    label_thresholds: dict[str, float]
    metrics: Metrics
    version: str

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        """Calibrated probability of the pump-then-dump outcome."""
        raw = self.booster.predict_proba(X[self.feature_names])[:, 1]
        return self.calibrator.predict(raw)


def _calibration_table(y_true: np.ndarray, p: np.ndarray, bins: int = 10) -> list[dict[str, float]]:
    edges = np.linspace(0.0, 1.0, bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1]), 0, bins - 1)
    rows: list[dict[str, float]] = []
    for b in range(bins):
        m = idx == b
        if not m.any():
            continue
        rows.append({
            "bin_lo": float(edges[b]), "bin_hi": float(edges[b + 1]),
            "n": int(m.sum()), "mean_pred": float(p[m].mean()),
            "observed_rate": float(y_true[m].mean()),
        })
    return rows


def train_susceptibility_model(split: Split, *, random_state: int = 42) -> TrainedModel:
    """Fit LightGBM on train, calibrate on calib, evaluate on test. Never touches test in fit."""
    # Enforce the no-leakage contract at the point of fitting, not just at build time.
    L.assert_no_label_leakage(FEATURE_COLUMNS)

    Xtr, ytr = split.train[FEATURE_COLUMNS], split.train[L.LABEL_COLUMN].to_numpy()
    Xca, yca = split.calib[FEATURE_COLUMNS], split.calib[L.LABEL_COLUMN].to_numpy()
    Xte, yte = split.test[FEATURE_COLUMNS], split.test[L.LABEL_COLUMN].to_numpy()

    clf = HistGradientBoostingClassifier(
        max_iter=400, learning_rate=0.03, max_leaf_nodes=31,
        min_samples_leaf=100, l2_regularization=1.0,
        class_weight="balanced",             # handle the ~2% base rate
        early_stopping=False, random_state=random_state,
    )
    clf.fit(Xtr, ytr)

    # Isotonic calibration on the held-out calib slice (raw model prob -> calibrated prob).
    raw_ca = clf.predict_proba(Xca)[:, 1]
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
    iso.fit(raw_ca, yca)

    raw_te = clf.predict_proba(Xte)[:, 1]
    cal_te = iso.predict(raw_te)

    base_rate = float(yte.mean())
    pr_auc = float(average_precision_score(yte, cal_te))
    metrics = Metrics(
        n_train=len(ytr), n_calib=len(yca), n_test=len(yte),
        base_rate_test=base_rate, pr_auc_test=pr_auc,
        roc_auc_test=float(roc_auc_score(yte, cal_te)),
        brier_calibrated_test=float(brier_score_loss(yte, cal_te)),
        lift_over_base=(pr_auc / base_rate) if base_rate > 0 else float("nan"),
        calibration_bins=_calibration_table(yte, cal_te),
        feature_importance_perm=_permutation_importance(clf, Xte, yte, random_state),
    )
    return TrainedModel(
        booster=clf, calibrator=iso, feature_names=list(FEATURE_COLUMNS),
        categorical_features=[],
        label_thresholds={
            "runup_threshold": L.RUNUP_THRESHOLD, "drawdown_threshold": L.DRAWDOWN_THRESHOLD,
            "runup_window": L.RUNUP_WINDOW, "drawdown_window": L.DRAWDOWN_WINDOW,
        },
        metrics=metrics,
        version=datetime.now(timezone.utc).strftime("v1_%Y%m%dT%H%M%SZ"),
    )


def _permutation_importance(
    clf: HistGradientBoostingClassifier, X: pd.DataFrame, y: np.ndarray,
    random_state: int, *, sample_cap: int = 30000, n_repeats: int = 3,
) -> dict[str, float]:
    """Permutation importance (drop in average-precision) on a capped test sample."""
    if len(X) > sample_cap:
        rng = np.random.default_rng(random_state)
        idx = rng.choice(len(X), size=sample_cap, replace=False)
        X, y = X.iloc[idx], y[idx]
    r = permutation_importance(
        clf, X, y, scoring="average_precision", n_repeats=n_repeats,
        random_state=random_state, n_jobs=1,
    )
    pairs = sorted(zip(X.columns, r.importances_mean), key=lambda kv: kv[1], reverse=True)
    return {n: round(float(v), 5) for n, v in pairs}


def save_model(model: TrainedModel, models_dir: Path | str) -> Path:
    """Persist the artifact plus a human-readable manifest sidecar. Returns the artifact path."""
    models_dir = Path(models_dir)
    models_dir.mkdir(parents=True, exist_ok=True)
    artifact = models_dir / f"susceptibility_{model.version}.joblib"
    joblib.dump(model, artifact)
    manifest: dict[str, Any] = {
        "version": model.version,
        "feature_names": model.feature_names,
        "categorical_features": model.categorical_features,
        "label_thresholds": model.label_thresholds,
        "metrics": asdict(model.metrics),
        "artifact": artifact.name,
    }
    (models_dir / f"susceptibility_{model.version}.manifest.json").write_text(
        json.dumps(manifest, indent=2)
    )
    (models_dir / "latest.txt").write_text(artifact.name)
    return artifact
