"""Build the committed deploy store: a small DuckDB + the model artifact.

What we ship and why:
  * symbols          — ALL rows (needed by the ticker resolver; tiny).
  * market_features  — only the most recent N_SESSIONS trade dates. Scoring reads the LATEST
                       precomputed feature row per ticker (Scorer._susceptibility does
                       `ORDER BY trade_date DESC LIMIT 1`), so the shipped values are byte-for-
                       byte the ones computed locally — nothing is recomputed on the box.
  * daily_prices     — DROPPED. It is the 1.47M-row bulk of the 231 MB store and is not read
                       at scoring time. (Production would keep it to recompute features daily;
                       for the demo the precomputed features suffice — see BACKLOG.)

N_SESSIONS=90 is comfortably more than any feature's lookback (max is the 60-session volume
z-score baseline), so even "score as of a recent past date" stays identical to local.

    PYTHONPATH=src python scripts/build_deploy_store.py
"""

from __future__ import annotations

import shutil
from pathlib import Path

import duckdb

from niveshak.market import config

N_SESSIONS = 90
DEPLOY_DIR = config.REPO_ROOT / "deploy"
DEPLOY_DB = DEPLOY_DIR / "niveshak.duckdb"
DEPLOY_MODELS = DEPLOY_DIR / "models"


def main() -> int:
    DEPLOY_DIR.mkdir(exist_ok=True)
    DEPLOY_MODELS.mkdir(exist_ok=True)
    if DEPLOY_DB.exists():
        DEPLOY_DB.unlink()

    src = str(config.DB_PATH)
    con = duckdb.connect(str(DEPLOY_DB))
    con.execute(f"ATTACH '{src}' AS srcdb (READ_ONLY)")

    cutoff = con.execute(
        "SELECT min(d) FROM (SELECT DISTINCT trade_date d FROM srcdb.market_features "
        f"ORDER BY d DESC LIMIT {N_SESSIONS})"
    ).fetchone()[0]

    con.execute("CREATE TABLE symbols AS SELECT * FROM srcdb.symbols")
    con.execute(
        "CREATE TABLE market_features AS SELECT * FROM srcdb.market_features "
        "WHERE trade_date >= ?", [cutoff],
    )
    con.execute("DETACH srcdb")
    n_sym = con.execute("SELECT count(*) FROM symbols").fetchone()[0]
    n_feat = con.execute("SELECT count(*) FROM market_features").fetchone()[0]
    span = con.execute(
        "SELECT count(DISTINCT trade_date), min(trade_date), max(trade_date) FROM market_features"
    ).fetchone()
    con.close()

    # copy the newest model artifact + manifest, and a latest.txt pointer
    models_src = config.REPO_ROOT / "models"
    latest = (models_src / "latest.txt").read_text().strip()
    shutil.copy2(models_src / latest, DEPLOY_MODELS / latest)
    manifest = latest.replace(".joblib", ".manifest.json")
    if (models_src / manifest).exists():
        shutil.copy2(models_src / manifest, DEPLOY_MODELS / manifest)
    (DEPLOY_MODELS / "latest.txt").write_text(latest)

    db_mb = DEPLOY_DB.stat().st_size / 1e6
    model_mb = (DEPLOY_MODELS / latest).stat().st_size / 1e6
    print(f"deploy store built: cutoff={cutoff}")
    print(f"  symbols={n_sym:,}  market_features={n_feat:,}  dates={span[0]} ({span[1]}..{span[2]})")
    print(f"  {DEPLOY_DB.name}={db_mb:.1f} MB   model={model_mb:.1f} MB   total={db_mb+model_mb:.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
