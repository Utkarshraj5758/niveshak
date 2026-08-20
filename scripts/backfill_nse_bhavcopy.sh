#!/usr/bin/env bash
# Backfill NSE "sec_bhavdata_full" daily files (OHLC + volume + delivery%) into a local cache.
#
# Why this source: sec_bhavdata_full_<DDMMYYYY>.csv is the single richest daily file NSE
# publishes for the cash segment. Unlike the UDiFF bhavcopy ZIP, it already contains
# DELIV_QTY and DELIV_PER, so one fetch per day covers everything daily_prices needs.
#
# Hard-won correctness rule (see docs/CLAUDE.md "things that will waste your time"):
#   NSE's CDN returns HTTP 200 for WEEKEND urls but serves the PREVIOUS trading day's file.
#   Weekday holidays return a real 404. So we NEVER trust the URL date: we validate the
#   DATE1 column inside the CSV and only accept a file whose internal trade date == the
#   requested date. Everything else is recorded as a non-trading day.
#
# The script is idempotent and resumable: a date already resolved (either a cached .csv or
# a .nodata marker) is skipped, so it can be re-run or interrupted freely.
#
# Usage: scripts/backfill_nse_bhavcopy.sh [START_YYYY-MM-DD] [END_YYYY-MM-DD]
set -u

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CACHE="$ROOT/data/raw/nse_sec_bhavdata"
MANIFEST="$ROOT/data/raw/_manifest/manifest.csv"
LOG="$ROOT/data/raw/_manifest/backfill.log"
mkdir -p "$CACHE" "$(dirname "$MANIFEST")"

START="${1:-$(date -d 'today -2 years' +%Y-%m-%d)}"
END="${2:-$(date -d 'today' +%Y-%m-%d)}"
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
BASE="https://nsearchives.nseindia.com/products/content/sec_bhavdata_full"

[ -f "$MANIFEST" ] || echo "date,url,http_code,bytes,status,internal_date,sha256_12,retrieved_at_utc" > "$MANIFEST"

log () { echo "[$(date -u +%H:%M:%S)] $*" | tee -a "$LOG"; }

# Month abbreviations as NSE writes them in DATE1 (e.g. 14-Aug-2026)
declare -a MON=(x Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec)

log "backfill start: $START .. $END  (cache=$CACHE)"
n_valid=0; n_nodata=0; n_skip=0; n_err=0; n_total=0

d="$START"
while [[ "$d" < "$END" || "$d" == "$END" ]]; do
  n_total=$((n_total+1))
  dow=$(date -d "$d" +%u)                       # 1=Mon .. 7=Sun
  ymd_c="$CACHE/$d.csv"
  ymd_n="$CACHE/$d.nodata"

  # Already resolved -> resume
  if [[ -f "$ymd_c" || -f "$ymd_n" ]]; then
    n_skip=$((n_skip+1)); d=$(date -d "$d +1 day" +%Y-%m-%d); continue
  fi
  # Weekend: markets closed, and the CDN echoes stale files here. Mark and move on.
  if [[ "$dow" == 6 || "$dow" == 7 ]]; then
    : > "$ymd_n"; n_nodata=$((n_nodata+1)); d=$(date -d "$d +1 day" +%Y-%m-%d); continue
  fi

  ddmmyyyy=$(date -d "$d" +%d%m%Y)
  url="${BASE}_${ddmmyyyy}.csv"
  tmp="$CACHE/.$d.tmp"
  code=$(curl -s -m 40 -A "$UA" -o "$tmp" -w "%{http_code}" "$url" 2>/dev/null)
  bytes=$(wc -c < "$tmp" 2>/dev/null | tr -d ' ')
  now=$(date -u +%Y-%m-%dT%H:%M:%SZ)

  status="err"; internal=""; sha=""
  if [[ "$code" == "200" ]]; then
    # Expected internal date string, e.g. 14-Aug-2026
    yyyy=${d:0:4}; mm=${d:5:2}; dd=${d:8:2}
    want="${dd}-${MON[10#$mm]}-${yyyy}"
    internal=$(sed -n '2p' "$tmp" | awk -F, '{gsub(/^ +| +$/,"",$3); print $3}')
    if [[ "$internal" == "$want" ]]; then
      mv -f "$tmp" "$ymd_c"
      sha=$(sha256sum "$ymd_c" | cut -c1-12)
      status="valid"; n_valid=$((n_valid+1))
    else
      # 200 but stale/echoed content (weekday holiday adjacent to weekend, or CDN echo)
      rm -f "$tmp"; : > "$ymd_n"; status="nodata_stale"; n_nodata=$((n_nodata+1))
    fi
  elif [[ "$code" == "404" ]]; then
    rm -f "$tmp"; : > "$ymd_n"; status="nodata_404"; n_nodata=$((n_nodata+1))
  else
    # transient error: do NOT write a marker, so a re-run retries this date
    rm -f "$tmp"; status="err_$code"; n_err=$((n_err+1))
    log "  WARN $d http=$code (will retry on re-run)"
  fi

  echo "$d,$url,$code,$bytes,$status,$internal,$sha,$now" >> "$MANIFEST"
  [[ "$status" == "valid" ]] && log "  ok   $d  ${bytes}B  sha=$sha"

  sleep 0.35                                     # be polite to NSE
  d=$(date -d "$d +1 day" +%Y-%m-%d)
done

log "backfill done: total=$n_total valid=$n_valid nodata=$n_nodata skipped=$n_skip errors=$n_err"
