"""Channel-message ingest for coordination detection.

Normalises inbound artifacts into `RawMessage`, stores them, and tags each with a resolved
ticker (via the existing resolver) so burst detection has a clean channel↔ticker mention
stream. Public channels only (CLAUDE.md rule 4); we never store private-group content.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import duckdb
from pydantic import BaseModel

from niveshak.parse.tip import Source

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS channel_messages (
    source      VARCHAR NOT NULL,
    channel_id  VARCHAR NOT NULL,
    message_id  VARCHAR NOT NULL,
    text        VARCHAR,
    posted_at   TIMESTAMP,
    PRIMARY KEY (source, channel_id, message_id)
);
CREATE TABLE IF NOT EXISTS channel_mentions (
    source      VARCHAR NOT NULL,
    channel_id  VARCHAR NOT NULL,
    message_id  VARCHAR NOT NULL,
    ticker      VARCHAR,
    posted_at   TIMESTAMP,
    PRIMARY KEY (source, channel_id, message_id)
);
"""


class RawMessage(BaseModel):
    source: Source
    channel_id: str
    message_id: str
    text: str
    posted_at: datetime


def init_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(SCHEMA_SQL)


def store_messages(con: duckdb.DuckDBPyConnection, messages: list[RawMessage]) -> int:
    """Insert-or-replace raw messages. Returns count."""
    init_schema(con)
    for m in messages:
        con.execute(
            "INSERT OR REPLACE INTO channel_messages VALUES (?, ?, ?, ?, ?)",
            [m.source, m.channel_id, m.message_id, m.text, m.posted_at],
        )
    return len(messages)


def tag_mentions(con: duckdb.DuckDBPyConnection, resolver: Any) -> int:
    """Resolve a ticker for every stored message into `channel_mentions`. Returns rows tagged.

    One best ticker per message (most tip messages push a single scrip). Unresolved messages
    are tagged with ticker NULL so they still count toward channel activity if needed.
    """
    init_schema(con)
    rows = con.execute(
        "SELECT source, channel_id, message_id, text, posted_at FROM channel_messages"
    ).fetchall()
    for source, channel_id, message_id, text, posted_at in rows:
        res = resolver.resolve(text or "")
        ticker = res.symbol if res else None
        con.execute(
            "INSERT OR REPLACE INTO channel_mentions VALUES (?, ?, ?, ?, ?)",
            [source, channel_id, message_id, ticker, posted_at],
        )
    return len(rows)
