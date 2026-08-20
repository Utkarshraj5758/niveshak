"""Rule parser: raw Hinglish/English tip text -> structured `Tip` (SPEC §3.2 v1).

Transparent and testable: regex + the YAML lexicons in `lexicons.yaml`. Each field has its
own small function so it can be unit-tested against hand-written tip strings. Two domain
rules from CLAUDE.md are honoured here:

* **Do not lowercase blindly** — the raw text (with its capitalisation) goes to the ticker
  resolver, which relies on ALL-CAPS tokens; only a lowercased *copy* feeds lexicon matching.
* **Do not strip emoji** — 🚀 and 🔥 are urgency features, matched from the lexicon.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from niveshak.parse.tip import Direction, Source, Tip, Urgency

_LEXICON_PATH = Path(__file__).parent / "lexicons.yaml"

# Small Hinglish marker set for language detection (Hindi written in Latin script).
_HINGLISH_MARKERS = frozenset({
    "ka", "ki", "ke", "me", "mein", "hai", "ho", "karo", "lelo", "lena", "bhai", "aaj",
    "kal", "turant", "pakka", "jaldi", "khabar", "tezi", "mandi", "abhi", "hafte", "saal",
    "bech", "becho", "kharido", "khareedo", "nahi", "nai", "wala", "wali", "sirf",
})

# target price: only when an explicit target keyword is present, so we never mistake a random
# number for a target. Captures e.g. "target 80", "tgt: 1500", "TP - 45.5", "target rs 120".
_TARGET_RE = re.compile(
    r"(?:target|tgt|trgt|tp)\s*(?:price)?\s*[:\-=]?\s*(?:rs\.?|inr|₹)?\s*"
    r"([0-9]{1,7}(?:\.[0-9]{1,2})?)",
    re.IGNORECASE,
)
_DAYS_RE = re.compile(r"([0-9]{1,3})\s*(day|days|din)\b", re.IGNORECASE)
_WEEKS_RE = re.compile(r"([0-9]{1,3})\s*(week|weeks|hafte|hafta)\b", re.IGNORECASE)
_MONTHS_RE = re.compile(r"([0-9]{1,3})\s*(month|months|mahine|mahina)\b", re.IGNORECASE)


@lru_cache(maxsize=1)
def load_lexicons(path: str | None = None) -> dict[str, Any]:
    """Load and cache the YAML lexicons."""
    p = Path(path) if path else _LEXICON_PATH
    with p.open(encoding="utf-8") as f:
        data: dict[str, Any] = yaml.safe_load(f)
    return data


def _term_matches(text_lower: str, term: str) -> bool:
    """Phrase/word match for alphabetic terms; substring for emoji/symbol terms."""
    if term and term[0].isalnum():
        return re.search(rf"(?<!\w){re.escape(term.lower())}(?!\w)", text_lower) is not None
    return term in text_lower           # emoji or symbol like 🚀, 100%


def _contains_any(text_lower: str, terms: list[str]) -> bool:
    return any(_term_matches(text_lower, t) for t in terms)


# --- individual field extractors (each unit-tested) --------------------------------

def detect_language(text: str) -> str:
    words = re.findall(r"[a-zA-Z]+", text.lower())
    if not words:
        return "en"
    has_hinglish = any(w in _HINGLISH_MARKERS for w in words)
    has_english = any(w not in _HINGLISH_MARKERS and len(w) > 1 for w in words)
    if has_hinglish and has_english:
        return "mixed"
    if has_hinglish:
        return "hi-Latn"
    return "en"


def detect_direction(text_lower: str, lex: dict[str, Any]) -> Direction:
    long_hit = _contains_any(text_lower, lex["direction"]["long"])
    short_hit = _contains_any(text_lower, lex["direction"]["short"])
    if long_hit and not short_hit:
        return "long"
    if short_hit and not long_hit:
        return "short"
    return "unclear"


def extract_target_price(text: str) -> float | None:
    m = _TARGET_RE.search(text)
    return float(m.group(1)) if m else None


def extract_horizon_days(text: str, lex: dict[str, Any]) -> int | None:
    text_lower = text.lower()
    if m := _DAYS_RE.search(text):
        return int(m.group(1))
    if m := _WEEKS_RE.search(text):
        return int(m.group(1)) * 7
    if m := _MONTHS_RE.search(text):
        return int(m.group(1)) * 30
    h = lex["horizon"]
    if _contains_any(text_lower, h["intraday"]):
        return 1
    if _contains_any(text_lower, h["positional"]):
        return 5
    if _contains_any(text_lower, h["long_term"]):
        return None
    return None


def detect_urgency(text_lower: str, lex: dict[str, Any]) -> Urgency:
    if _contains_any(text_lower, lex["urgency"]["high"]):
        return "high"
    if _contains_any(text_lower, lex["urgency"]["medium"]):
        return "medium"
    return "low"


def has_guarantee_claim(text_lower: str, lex: dict[str, Any]) -> bool:
    return _contains_any(text_lower, lex["guarantee"])


def has_insider_claim(text_lower: str, lex: dict[str, Any]) -> bool:
    return _contains_any(text_lower, lex["insider"])


def has_disclosure(text_lower: str, lex: dict[str, Any]) -> bool:
    return _contains_any(text_lower, lex["disclosure"])


# --- assembly -------------------------------------------------------------------

def parse_message(
    raw_text: str, *, source: Source = "manual", channel_id: str | None = None,
    posted_at: datetime | None = None, tip_id: str | None = None,
    resolver: Any | None = None,
) -> Tip:
    """Parse one message into a Tip. `resolver` is a TickerResolver (or None -> ticker None).

    Emoji are preserved and the resolver sees the original-case text; lexicon matching uses a
    lowercased copy.
    """
    lex = load_lexicons()
    text_lower = raw_text.lower()

    ticker: str | None = None
    if resolver is not None:
        res = resolver.resolve(raw_text)
        ticker = res.symbol if res else None

    return Tip(
        tip_id=tip_id or uuid.uuid4().hex,
        source=source,
        channel_id=channel_id,
        raw_text=raw_text,
        language=detect_language(raw_text),
        ticker=ticker,
        direction=detect_direction(text_lower, lex),
        target_price=extract_target_price(raw_text),
        horizon_days=extract_horizon_days(raw_text, lex),
        urgency=detect_urgency(text_lower, lex),
        guarantee_claim=has_guarantee_claim(text_lower, lex),
        insider_claim=has_insider_claim(text_lower, lex),
        disclosure_present=has_disclosure(text_lower, lex),
        posted_at=posted_at or datetime.now(timezone.utc),
    )
