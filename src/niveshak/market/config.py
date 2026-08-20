"""Filesystem layout and shared constants for the market data layer.

Everything the backfill and loaders touch is anchored to the repo `data/` directory so the
bash bootstrap script (`scripts/backfill_nse_bhavcopy.sh`) and the Python modules share one
cache. Nothing here reaches the network; it only decides where bytes land.
"""

from __future__ import annotations

from pathlib import Path

# repo root = .../niveshak (three parents up from this file: market -> niveshak -> src -> root)
REPO_ROOT = Path(__file__).resolve().parents[3]

DATA_DIR = REPO_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
# Daily NSE "sec_bhavdata_full" files, one per trading day, named <YYYY-MM-DD>.csv.
# Non-trading days get a zero-byte <YYYY-MM-DD>.nodata marker so re-runs skip them.
NSE_BHAVDATA_DIR = RAW_DIR / "nse_sec_bhavdata"
SYMBOLS_DIR = RAW_DIR / "symbols"
MANIFEST_DIR = RAW_DIR / "_manifest"
MANIFEST_CSV = MANIFEST_DIR / "manifest.csv"

DB_PATH = DATA_DIR / "niveshak.duckdb"

# A browser UA is mandatory: NSE archives reject non-browser agents (see CLAUDE.md).
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

# NSE cash-segment "security-wise delivery position": OHLC + volume + delivery% in one file.
NSE_BHAVDATA_URL = "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{ddmmyyyy}.csv"

# Symbol masters (public CSVs, refreshed by NSE daily/weekly).
NSE_EQUITY_MASTER_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
NSE_SME_MASTER_URL = "https://nsearchives.nseindia.com/content/equities/SME_EQUITY_L.csv"

# NSE series that denote SME (Emerge) scrips. is_sme is set from these everywhere.
SME_SERIES = frozenset({"SM", "ST"})


def ensure_dirs() -> None:
    """Create every cache directory. Safe to call repeatedly."""
    for d in (NSE_BHAVDATA_DIR, SYMBOLS_DIR, MANIFEST_DIR):
        d.mkdir(parents=True, exist_ok=True)
