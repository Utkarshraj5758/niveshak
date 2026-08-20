"""NSE symbol master loader.

Downloads the two public NSE equity lists and normalises them into the ``symbols`` table:

* ``EQUITY_L.csv``     — mainboard equities.
* ``SME_EQUITY_L.csv`` — Emerge (SME) equities; ``is_sme`` is set for these.

Ticker resolution (rapidfuzz over this master) is Day 2. This module only loads the master;
it does not resolve free text. Files are cached under ``data/raw/symbols/`` with a fetch
timestamp, matching the provenance rule in docs/DATA_SOURCES.md.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd
import requests

from niveshak.market import config, db

# EQUITY_L / SME_EQUITY_L share this header (note the leading spaces NSE adds).
_MASTER_COLS = {
    "SYMBOL": "symbol",
    "NAME OF COMPANY": "name",
    "SERIES": "series",
    "DATE OF LISTING": "date_of_listing",
    "PAID UP VALUE": "paid_up_value",
    "MARKET LOT": "market_lot",
    "ISIN NUMBER": "isin",
    "FACE VALUE": "face_value",
}


def download_master(url: str, dest: Path, *, timeout: float = 30.0) -> Path:
    """Fetch a symbol-master CSV to ``dest`` (browser UA required)."""
    config.ensure_dirs()
    resp = requests.get(url, headers={"User-Agent": config.USER_AGENT}, timeout=timeout)
    resp.raise_for_status()
    dest.write_bytes(resp.content)
    return dest


def download_all(*, timeout: float = 30.0) -> dict[str, Path]:
    """Download mainboard + SME masters. Returns {name: cached_path}."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    out: dict[str, Path] = {}
    for name, url in (
        ("nse_equity", config.NSE_EQUITY_MASTER_URL),
        ("nse_sme", config.NSE_SME_MASTER_URL),
    ):
        dest = config.SYMBOLS_DIR / f"{name}_{stamp}.csv"
        try:
            out[name] = download_master(url, dest)
        except requests.RequestException as exc:  # keep going if one list is down
            print(f"[symbols] WARN could not fetch {name}: {exc}")
    return out


def _parse_master(path: Path, *, source_url: str) -> pd.DataFrame:
    """Normalise one master CSV into the ``symbols`` table shape."""
    raw = pd.read_csv(path, dtype=str, skipinitialspace=True)
    raw.columns = [c.strip() for c in raw.columns]
    raw = raw[[c for c in _MASTER_COLS if c in raw.columns]].rename(columns=_MASTER_COLS)
    for c in raw.columns:
        raw[c] = raw[c].astype("string").str.strip()

    df = pd.DataFrame({
        "exchange": "NSE",
        "symbol": raw.get("symbol"),
        "series": raw.get("series"),
        "name": raw.get("name"),
        "isin": raw.get("isin"),
        "face_value": pd.to_numeric(raw.get("face_value"), errors="coerce"),
        "market_lot": pd.to_numeric(raw.get("market_lot"), errors="coerce").astype("Int64"),
        "date_of_listing": pd.to_datetime(
            raw.get("date_of_listing"), format="%d-%b-%Y", errors="coerce"
        ).dt.date,
        "is_sme": raw.get("series").isin(config.SME_SERIES) if "series" in raw else False,
        "source_url": source_url,
        "loaded_at": datetime.now(timezone.utc),
    })
    return df.dropna(subset=["symbol", "series"])


def load_into_db(
    con: duckdb.DuckDBPyConnection, paths: dict[str, Path] | None = None
) -> int:
    """Load cached masters into ``symbols``. Downloads them first if not provided."""
    if paths is None:
        paths = download_all()
    url_by_name = {
        "nse_equity": config.NSE_EQUITY_MASTER_URL,
        "nse_sme": config.NSE_SME_MASTER_URL,
    }
    total = 0
    for name, path in paths.items():
        frame = _parse_master(path, source_url=url_by_name.get(name, ""))
        total += db.load_symbol_frame(con, frame)
    return total
