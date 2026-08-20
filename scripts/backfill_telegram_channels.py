"""Backfill public Telegram tip channels for coordination detection (credential-gated).

Needs Telegram *API* credentials (api_id/api_hash from https://my.telegram.org) — distinct
from the bot token — because Telethon reads channels as a user client. Public channels only.

    export TELEGRAM_API_ID=... TELEGRAM_API_HASH=...
    PYTHONPATH=src python scripts/backfill_telegram_channels.py \
        --days 90 @channel_one @channel_two ...

Stores messages, tags each with a resolved ticker, and prints the current Pump Watchlist.
Telethon is an optional dependency (`pip install telethon`); it is not required to run the
scorer/API — coordination stays dormant (no bursts) until this archive exists.
"""

from __future__ import annotations

import argparse
import asyncio
import os
from datetime import datetime, timedelta, timezone

from niveshak.graph.burst import BurstProvider
from niveshak.ingest.messages import RawMessage, store_messages, tag_mentions
from niveshak.market import db
from niveshak.parse.tickers import TickerResolver


async def _backfill(channels: list[str], days: int) -> None:
    try:
        from telethon import TelegramClient  # type: ignore[import-not-found]
    except ImportError:
        raise SystemExit("Telethon not installed. `pip install telethon` to run the backfill.")

    api_id = os.environ.get("TELEGRAM_API_ID")
    api_hash = os.environ.get("TELEGRAM_API_HASH")
    if not (api_id and api_hash):
        raise SystemExit("Set TELEGRAM_API_ID and TELEGRAM_API_HASH (my.telegram.org).")

    con = db.connect()
    since = datetime.now(timezone.utc) - timedelta(days=days)
    total = 0
    async with TelegramClient("niveshak_ingest", int(api_id), api_hash) as client:  # type: ignore[arg-type]
        for ch in channels:
            batch: list[RawMessage] = []
            async for msg in client.iter_messages(ch, offset_date=None):
                if msg.date and msg.date < since:
                    break
                if not msg.message:
                    continue
                batch.append(RawMessage(
                    source="telegram", channel_id=str(ch), message_id=str(msg.id),
                    text=msg.message, posted_at=msg.date,
                ))
            total += store_messages(con, batch)
            print(f"  {ch}: stored {len(batch)} messages")

    tagged = tag_mentions(con, TickerResolver.from_duckdb(con))
    print(f"stored {total} messages, tagged {tagged} mentions")
    print("Current Pump Watchlist (coordination bursts):")
    for s in BurstProvider(con).watchlist(limit=15):
        z = "inf" if s.z == float("inf") else f"{s.z:.1f}"
        print(f"  {s.ticker:12s} {s.n_channels} channels/48h  z={z}")
    con.close()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("channels", nargs="+", help="public channel @usernames or ids")
    p.add_argument("--days", type=int, default=90)
    args = p.parse_args()
    asyncio.run(_backfill(args.channels, args.days))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
