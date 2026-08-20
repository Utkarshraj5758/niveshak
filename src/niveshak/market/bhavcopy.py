"""NSE daily bhavcopy downloader with a local, resumable cache.

This is the canonical in-repo downloader. The 2-year backfill is bootstrapped by
``scripts/backfill_nse_bhavcopy.sh`` (so downloading can start with zero Python setup), but
that script and this module share the exact same cache layout and validation rule, so this
module is what the rest of the pipeline (and daily incremental fetches) use going forward.

The one correctness rule that matters (see CLAUDE.md): NSE's CDN answers WEEKEND urls with
HTTP 200 but serves the *previous* trading day's file, while weekday holidays 404. We never
trust the URL date — we validate the ``DATE1`` value inside the CSV and only accept a file
whose internal trade date equals the date we asked for. Weekends are skipped up front.
"""

from __future__ import annotations

import csv
import hashlib
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

import requests
from pydantic import BaseModel

from niveshak.market import config

Status = Literal["valid", "nodata", "skipped", "error"]

_MON = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


class DayResult(BaseModel):
    """Outcome of resolving one calendar date."""

    day: date
    status: Status
    http_code: int | None = None
    bytes: int = 0
    internal_date: str | None = None
    path: str | None = None
    note: str | None = None


def _expected_internal_date(d: date) -> str:
    """The DATE1 string NSE writes for date ``d``, e.g. 2026-08-14 -> '14-Aug-2026'."""
    return f"{d.day:02d}-{_MON[d.month]}-{d.year}"


def _csv_path(d: date) -> Path:
    return config.NSE_BHAVDATA_DIR / f"{d.isoformat()}.csv"


def _nodata_path(d: date) -> Path:
    return config.NSE_BHAVDATA_DIR / f"{d.isoformat()}.nodata"


def _first_data_date(text: str) -> str | None:
    """Return the trimmed DATE1 of the first data row, or None if there isn't one."""
    reader = csv.reader(text.splitlines())
    rows = iter(reader)
    next(rows, None)  # header
    first = next(rows, None)
    if not first or len(first) < 3:
        return None
    return first[2].strip()


def _make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": config.USER_AGENT, "Accept": "text/csv,*/*"})
    return s


def _append_manifest(r: DayResult, url: str) -> None:
    config.ensure_dirs()
    new = not config.MANIFEST_CSV.exists()
    with config.MANIFEST_CSV.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(
                ["date", "url", "http_code", "bytes", "status", "internal_date",
                 "sha256_12", "retrieved_at_utc"]
            )
        sha = ""
        if r.status == "valid" and r.path:
            sha = hashlib.sha256(Path(r.path).read_bytes()).hexdigest()[:12]
        w.writerow(
            [r.day.isoformat(), url, r.http_code or "", r.bytes, r.status,
             r.internal_date or "", sha, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")]
        )


def fetch_day(
    d: date, *, session: requests.Session | None = None, force: bool = False,
    timeout: float = 40.0,
) -> DayResult:
    """Resolve one calendar date: download+validate, mark non-trading, or skip if cached."""
    config.ensure_dirs()
    csv_path, nodata_path = _csv_path(d), _nodata_path(d)

    if not force and (csv_path.exists() or nodata_path.exists()):
        status: Status = "skipped"
        return DayResult(day=d, status=status,
                         path=str(csv_path) if csv_path.exists() else None,
                         note="already cached")

    # Weekend: closed, and the CDN echoes stale files here. Mark without a request.
    if d.weekday() >= 5:  # 5=Sat, 6=Sun
        nodata_path.touch()
        r = DayResult(day=d, status="nodata", note="weekend")
        _append_manifest(r, url="(skipped-weekend)")
        return r

    sess = session or _make_session()
    url = config.NSE_BHAVDATA_URL.format(ddmmyyyy=d.strftime("%d%m%Y"))
    try:
        resp = sess.get(url, timeout=timeout)
    except requests.RequestException as exc:
        # Transient: do NOT write a marker, so a re-run retries this date.
        r = DayResult(day=d, status="error", note=f"request failed: {exc}")
        _append_manifest(r, url)
        return r

    r_bytes = len(resp.content)
    if resp.status_code == 404:
        nodata_path.touch()
        r = DayResult(day=d, status="nodata", http_code=404, bytes=r_bytes, note="404 holiday")
        _append_manifest(r, url)
        return r
    if resp.status_code != 200:
        r = DayResult(day=d, status="error", http_code=resp.status_code, bytes=r_bytes,
                      note="unexpected status")
        _append_manifest(r, url)
        return r

    internal = _first_data_date(resp.text)
    want = _expected_internal_date(d)
    if internal == want:
        csv_path.write_bytes(resp.content)
        r = DayResult(day=d, status="valid", http_code=200, bytes=r_bytes,
                      internal_date=internal, path=str(csv_path))
        _append_manifest(r, url)
        return r

    # 200 but the file's trade date isn't the one we asked for -> stale CDN echo (weekend
    # boundary) or an empty/holiday page. Treat as a confirmed non-trading day.
    nodata_path.touch()
    r = DayResult(day=d, status="nodata", http_code=200, bytes=r_bytes,
                  internal_date=internal, note="stale/echoed content")
    _append_manifest(r, url)
    return r


def backfill(
    start: date, end: date, *, force: bool = False, pause: float = 0.35,
) -> list[DayResult]:
    """Fetch every date in [start, end]. Idempotent and resumable. Returns per-day results."""
    session = _make_session()
    results: list[DayResult] = []
    d = start
    while d <= end:
        res = fetch_day(d, session=session, force=force)
        results.append(res)
        # Only sleep after a real network hit; cached/weekend days are free.
        if res.status in ("valid", "nodata", "error") and res.http_code is not None:
            time.sleep(pause)
        d += timedelta(days=1)
    return results


def two_year_range(today: date | None = None) -> tuple[date, date]:
    """The default backfill window: two years back through today."""
    end = today or date.today()
    try:
        start = end.replace(year=end.year - 2)
    except ValueError:  # Feb 29
        start = end.replace(year=end.year - 2, day=28)
    return start, end
