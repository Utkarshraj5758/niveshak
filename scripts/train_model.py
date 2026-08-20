"""Train the scrip-susceptibility model and write reports/model_v1.md.

Enforces the Day-1 gate: if test PR-AUC is at or below the test base rate, the model has no
signal (or a leak is masking one) — we STOP with a non-zero exit and say so in the report,
rather than shipping a meaningless number.

Run:  PYTHONPATH=src python scripts/train_model.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

from niveshak.market import db
from niveshak.score import dataset as D
from niveshak.score import labels as L
from niveshak.score import model as M

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = REPO_ROOT / "reports"
MODELS_DIR = REPO_ROOT / "models"


def _fmt_pct(x: float) -> str:
    return f"{x * 100:.2f}%"


def write_report(model: M.TrainedModel, split: D.Split, *, passed: bool) -> Path:
    m = model.metrics
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    lines.append("# Model v1 — scrip-susceptibility (market-only, weak labels)\n")
    lines.append(f"_Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC} · artifact `{model.version}`_\n")

    verdict = "PASS ✅" if passed else "FAIL — STOP, hunt for leakage ⛔"
    lines.append("## Headline\n")
    lines.append(f"- **Gate:** {verdict}")
    lines.append(f"- **Test PR-AUC: `{m.pr_auc_test:.4f}`**")
    lines.append(f"- **Test base rate (positive prevalence): `{m.base_rate_test:.4f}` ({_fmt_pct(m.base_rate_test)})**")
    lines.append(f"- **Lift over base (PR-AUC / base rate): `{m.lift_over_base:.2f}×`**  "
                 "(a no-skill classifier scores PR-AUC ≈ base rate, so 1.0× = no signal)")
    lines.append(f"- Test ROC-AUC: `{m.roc_auc_test:.4f}` · Brier (calibrated): `{m.brier_calibrated_test:.4f}`\n")

    lines.append("## Label (training-only, forward-looking)\n")
    lines.append("Weak outcome rule — never a feature (`assert_no_label_leakage` enforced in code):")
    lines.append(f"- positive if close rises ≥ **{_fmt_pct(L.RUNUP_THRESHOLD)}** within "
                 f"**{L.RUNUP_WINDOW}** sessions, then falls ≥ **{_fmt_pct(L.DRAWDOWN_THRESHOLD)}** "
                 f"from that peak within the next **{L.DRAWDOWN_WINDOW}** sessions.\n")

    lines.append("## Temporal split (never random)\n")
    lines.append(f"- Embargo before test: **{split.embargo_days} days** "
                 "(≥ the forward label horizon, so no train/calib label window reaches into test).")
    lines.append(f"- calib starts `{split.calib_start:%Y-%m-%d}` · test starts `{split.test_start:%Y-%m-%d}`")
    lines.append(f"- rows — train **{m.n_train:,}**, calib **{m.n_calib:,}**, test **{m.n_test:,}**\n")

    lines.append("## Calibration (predicted vs observed on test)\n")
    lines.append("| pred bin | n | mean predicted | observed rate |")
    lines.append("|---|---:|---:|---:|")
    for b in m.calibration_bins:
        lines.append(f"| {b['bin_lo']:.1f}–{b['bin_hi']:.1f} | {b['n']:,} | "
                     f"{b['mean_pred']:.3f} | {b['observed_rate']:.3f} |")
    lines.append("")

    lines.append("## Feature importance (permutation, drop in average-precision on test)\n")
    lines.append("| feature | Δ avg-precision when shuffled |")
    lines.append("|---|---:|")
    for name, val in model.metrics.feature_importance_perm.items():
        lines.append(f"| {name} | {val:.5f} |")
    lines.append("")

    lines.append("## Honest caveats\n")
    lines.append("- **Model:** scikit-learn `HistGradientBoostingClassifier` (LightGBM's native lib "
                 "segfaults on this build machine — missing OpenMP/VC++ runtime). Same histogram-GBDT "
                 "family; swap back to LightGBM once the runtime is fixed.")
    lines.append("- Labels are **weak** (outcome-rule), not SEBI-confirmed. This measures how well "
                 "market microstructure predicts a pump-then-dump *shape*, not confirmed manipulation.")
    lines.append("- `upper_circuit_count_10d` is a locked-price proxy; `liquidity_bucket` is a "
                 "trailing-turnover stand-in for market cap (no shares-outstanding in bhavcopy).")
    lines.append("- `days_since_listing` is ~62% populated (symbol master coverage gap).")

    path = REPORTS_DIR / "model_v1.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main() -> int:
    con = db.connect()
    print("[train] building labelled dataset…")
    df = D.build_labeled_dataset(con)
    print(f"[train] labelled rows: {len(df):,}  positives: {int(df[L.LABEL_COLUMN].sum()):,} "
          f"({df[L.LABEL_COLUMN].mean() * 100:.2f}%)")
    split = D.temporal_split(df)
    print(f"[train] split — train={len(split.train):,} calib={len(split.calib):,} test={len(split.test):,}")
    if min(len(split.train), len(split.calib), len(split.test)) == 0:
        print("[train] ERROR: an empty split segment — check date coverage.", file=sys.stderr)
        return 2

    model = M.train_susceptibility_model(split)
    m = model.metrics
    passed = m.pr_auc_test > m.base_rate_test

    report = write_report(model, split, passed=passed)
    print(f"[train] PR-AUC={m.pr_auc_test:.4f}  base_rate={m.base_rate_test:.4f}  "
          f"lift={m.lift_over_base:.2f}x  ->  {'PASS' if passed else 'FAIL'}")
    print(f"[train] report: {report}")

    if not passed:
        print("[train] GATE FAILED: PR-AUC <= base rate. STOP and hunt for leakage before "
              "continuing. Model NOT saved.", file=sys.stderr)
        con.close()
        return 1

    artifact = M.save_model(model, MODELS_DIR)
    print(f"[train] saved artifact: {artifact}")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
