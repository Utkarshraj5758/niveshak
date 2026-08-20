"""The `Tip` data contract — the spine of the system (mirrors CLAUDE.md exactly).

Everything upstream produces a Tip; everything downstream consumes one. Pydantic v2 so the
shape is validated at the boundary rather than trusted. Do not change fields without
updating docs/SPEC.md and CLAUDE.md.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

Source = Literal["telegram", "youtube", "x", "whatsapp", "manual"]
Direction = Literal["long", "short", "unclear"]
Urgency = Literal["low", "medium", "high"]


class Tip(BaseModel):
    tip_id: str
    source: Source
    channel_id: str | None = None
    raw_text: str
    language: str                      # "hi-Latn" | "en" | "mixed"
    ticker: str | None = None          # resolved NSE/BSE symbol, or None when unsure
    direction: Direction
    target_price: float | None = None
    horizon_days: int | None = None
    urgency: Urgency
    guarantee_claim: bool
    insider_claim: bool
    disclosure_present: bool
    posted_at: datetime
