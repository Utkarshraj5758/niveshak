"""DuckDB schema and loaders for the market feature store.

Two tables live here:

* ``symbols``      — the NSE/BSE symbol master (ticker -> company, listing date, is_sme).
* ``daily_prices`` — one row per (exchange, symbol, series, trade_date) from the NSE
                     ``sec_bhavdata_full`` daily files: OHLC, volume, and delivery%.

Both loaders are idempotent: they use ``INSERT OR REPLACE`` against the primary key, so
re-loading a cached file (or re-running the whole backfill) never duplicates rows.

Feature computation is deliberately NOT here — that is Day 1 afternoon. This module only
gets clean, typed rows into DuckDB.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from niveshak.market import config

# ---- raw sec_bhavdata_full columns, in file order, mapped to our snake_case names ----
_DAILY_SRC_COLS = [
    "SYMBOL", "SERIES", "DATE1", "PREV_CLOSE", "OPEN_PRICE", "HIGH_PRICE", "LOW_PRICE",
    "LAST_PRICE", "CLOSE_PRICE", "AVG_PRICE", "TTL_TRD_QNTY", "TURNOVER_LACS",
    "NO_OF_TRADES", "DELIV_QTY", "DELIV_PER",
]

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS symbols (
    exchange        VARCHAR NOT NULL,        -- 'NSE' | 'BSE'
    symbol          VARCHAR NOT NULL,
    series          VARCHAR,
    name            VARCHAR,
    isin            VARCHAR,
    face_value      DOUBLE,
    market_lot      BIGINT,
    date_of_listing DATE,
    is_sme          BOOLEAN NOT NULL DEFAULT FALSE,
    source_url      VARCHAR,
    loaded_at       TIMESTAMP DEFAULT now(),
    PRIMARY KEY (exchange, symbol, series)
);

CREATE TABLE IF NOT EXISTS daily_prices (
    exchange         VARCHAR NOT NULL,       -- 'NSE' | 'BSE'
    symbol           VARCHAR NOT NULL,
    series           VARCHAR NOT NULL,
    trade_date       DATE    NOT NULL,
    prev_close       DOUBLE,
    open             DOUBLE,
    high             DOUBLE,
    low              DOUBLE,
    last             DOUBLE,
    close            DOUBLE,
    avg_price        DOUBLE,
    total_traded_qty BIGINT,
    turnover_lacs    DOUBLE,
    num_trades       BIGINT,
    deliv_qty        BIGINT,
    deliv_pct        DOUBLE,                 -- NULL for series that don't report delivery
    is_sme           BOOLEAN NOT NULL DEFAULT FALSE,
    source_file      VARCHAR,
    PRIMARY KEY (exchange, symbol, series, trade_date)
);
"""


def connect(db_path: Path | str | None = None) -> duckdb.DuckDBPyConnection:
    """Open (creating if needed) the DuckDB store and ensure the schema exists."""
    config.ensure_dirs()
    path = Path(db_path) if db_path is not None else config.DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    con.execute(SCHEMA_SQL)
    return con


def _clean_str_series(s: pd.Series) -> pd.Series:
    """Strip the leading spaces NSE puts after every comma."""
    return s.astype("string").str.strip()


def load_daily_file(con: duckdb.DuckDBPyConnection, path: Path | str) -> int:
    """Load one cached sec_bhavdata_full CSV into ``daily_prices``. Returns rows written.

    Robust to NSE quirks: leading spaces in every field, and ``-`` placeholders in the
    delivery columns for series that don't report delivery (coerced to NULL).
    """
    path = Path(path)
    raw = pd.read_csv(path, dtype=str, skipinitialspace=True)
    raw.columns = [c.strip() for c in raw.columns]
    missing = [c for c in _DAILY_SRC_COLS if c not in raw.columns]
    if missing:
        raise ValueError(f"{path.name}: missing expected columns {missing}")

    for c in _DAILY_SRC_COLS:
        raw[c] = _clean_str_series(raw[c])

    num = lambda col: pd.to_numeric(raw[col], errors="coerce")  # noqa: E731
    df = pd.DataFrame({
        "exchange": "NSE",
        "symbol": raw["SYMBOL"],
        "series": raw["SERIES"],
        "trade_date": pd.to_datetime(raw["DATE1"], format="%d-%b-%Y", errors="coerce").dt.date,
        "prev_close": num("PREV_CLOSE"),
        "open": num("OPEN_PRICE"),
        "high": num("HIGH_PRICE"),
        "low": num("LOW_PRICE"),
        "last": num("LAST_PRICE"),
        "close": num("CLOSE_PRICE"),
        "avg_price": num("AVG_PRICE"),
        "total_traded_qty": num("TTL_TRD_QNTY").astype("Int64"),
        "turnover_lacs": num("TURNOVER_LACS"),
        "num_trades": num("NO_OF_TRADES").astype("Int64"),
        "deliv_qty": num("DELIV_QTY").astype("Int64"),
        "deliv_pct": num("DELIV_PER"),
        "is_sme": raw["SERIES"].isin(config.SME_SERIES),
        "source_file": path.name,
    })
    # Drop rows we can't key on (bad symbol/series/date).
    df = df.dropna(subset=["symbol", "series", "trade_date"])
    if df.empty:
        return 0

    con.register("_daily_df", df)
    con.execute("INSERT OR REPLACE INTO daily_prices SELECT * FROM _daily_df")
    con.unregister("_daily_df")
    return len(df)


def load_daily_dir(
    con: duckdb.DuckDBPyConnection, cache_dir: Path | str | None = None
) -> tuple[int, int]:
    """Load every cached daily CSV. Returns (files_loaded, rows_written)."""
    cache = Path(cache_dir) if cache_dir is not None else config.NSE_BHAVDATA_DIR
    files = sorted(cache.glob("*.csv"))
    total_rows = 0
    for f in files:
        total_rows += load_daily_file(con, f)
    return len(files), total_rows


def load_symbol_frame(
    con: duckdb.DuckDBPyConnection, df: pd.DataFrame
) -> int:
    """Insert-or-replace a prepared symbols frame (see symbols.py). Returns rows written."""
    if df.empty:
        return 0
    con.register("_sym_df", df)
    con.execute("INSERT OR REPLACE INTO symbols SELECT * FROM _sym_df")
    con.unregister("_sym_df")
    return len(df)
