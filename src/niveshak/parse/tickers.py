"""Ticker resolution: free-text mention -> NSE symbol, or None when unsure.

This is the highest-risk silent-failure point in the system, so the resolver is built to
*prefer None over a plausible guess*. It resolves in three ordered stages, each more
cautious than raw fuzzy matching:

1. **Exact ticker token.** Tips write real tickers in caps ("buy SUZLON"). An ALL-CAPS token
   that is an actual symbol is accepted with full confidence. A Titlecase word ("Reliance")
   is treated as a company reference, not a ticker — which is why bare "Reliance" stays
   ambiguous while "RELIANCE" resolves.
2. **Curated alias.** A small, documented nickname map (SBI->SBIN, HUL->HINDUNILVR, ...) for
   names fuzzy matching can't reach. Aliases are explicit and auditable, never guessed.
3. **Fuzzy match with an ambiguity guard.** rapidfuzz token_sort_ratio over the symbol
   master. A match is returned only if it clears a confidence threshold AND beats the
   second-best *distinct* symbol by a margin. "Bajaj" (Finance/Finserv/Auto) ties across
   siblings, so it returns None rather than picking one — a wrong ticker is worse than none.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from rapidfuzz import fuzz

# Corporate/geographic boilerplate stripped before fuzzy name matching, so e.g.
# "Maruti Suzuki" matches "Maruti Suzuki India Limited". ("indian" is NOT stripped — it is a
# meaningful token in IRCTC / IRFC / IREDA names.)
_SUFFIX_STOPWORDS = frozenset({"limited", "ltd", "the", "company", "co", "india"})

# Confidence gates (0-100). Tuned against tests/test_ticker_resolution.py.
DEFAULT_THRESHOLD = 86.0
DEFAULT_MARGIN = 6.0

# Curated nicknames. Keys are alias-normalised (lowercase, punctuation kept only as '&').
# Every entry is a deliberate, auditable decision — not a fuzzy guess.
ALIASES: dict[str, str] = {
    "sbi": "SBIN",
    "hul": "HINDUNILVR",
    "infy": "INFY",
    "l&t": "LT",
    "lt": "LT",
    "dmart": "DMART",
    "lic": "LICI",
    "maruti": "MARUTI",
}

_CAPS_TOKEN = re.compile(r"[A-Z][A-Z0-9&\-]{2,}")


@dataclass(frozen=True)
class Resolution:
    symbol: str
    score: float
    method: str          # "exact" | "alias" | "fuzzy"
    name: str | None = None


def _alias_key(s: str) -> str:
    return re.sub(r"[^a-z0-9&]", "", s.lower())


def _norm_name(s: str) -> str:
    toks = re.sub(r"[^a-z0-9 ]", " ", s.lower()).split()
    kept = [t for t in toks if t not in _SUFFIX_STOPWORDS]
    return " ".join(kept) if kept else " ".join(toks)


class TickerResolver:
    def __init__(
        self, records: list[tuple[str, str]], *,
        threshold: float = DEFAULT_THRESHOLD, margin: float = DEFAULT_MARGIN,
    ) -> None:
        self.threshold = threshold
        self.margin = margin
        self._symbols: set[str] = set()
        self._name_by_symbol: dict[str, str] = {}
        self._candidates: list[tuple[str, str]] = []  # (symbol, norm_name)
        for symbol, name in records:
            symbol = symbol.strip().upper()
            if not symbol:
                continue
            self._symbols.add(symbol)
            self._name_by_symbol[symbol] = name
            self._candidates.append((symbol, _norm_name(name)))

    @classmethod
    def from_records(cls, records: list[tuple[str, str]], **kw: float) -> TickerResolver:
        return cls(records, **kw)

    @classmethod
    def from_duckdb(cls, con: object, **kw: float) -> TickerResolver:
        """Build from the loaded `symbols` table (mainboard + SME)."""
        rows = con.execute(  # type: ignore[attr-defined]
            "SELECT DISTINCT symbol, name FROM symbols WHERE name IS NOT NULL"
        ).fetchall()
        return cls([(r[0], r[1]) for r in rows], **kw)

    # --- resolution stages -------------------------------------------------------

    def _exact_token(self, text: str) -> Resolution | None:
        hits = {t for t in _CAPS_TOKEN.findall(text) if t in self._symbols}
        if len(hits) == 1:
            sym = next(iter(hits))
            return Resolution(sym, 100.0, "exact", self._name_by_symbol.get(sym))
        return None  # zero hits -> fall through; multiple -> ambiguous, refuse

    def _alias(self, text: str) -> Resolution | None:
        sym = ALIASES.get(_alias_key(text))
        if sym is None:
            return None
        return Resolution(sym, 99.0, "alias", self._name_by_symbol.get(sym))

    def _fuzzy(self, text: str) -> Resolution | None:
        q = _norm_name(text)
        if not q:
            return None
        # Match names only. Symbols are handled by the caps-only exact stage, so a Titlecase
        # word like "Reliance" is scored against "reliance industries" (ambiguous), not
        # against the bare symbol "RELIANCE" (which would spuriously score 100).
        best_by_symbol: dict[str, float] = {}
        for symbol, norm_name in self._candidates:
            score = fuzz.token_sort_ratio(q, norm_name)
            if score > best_by_symbol.get(symbol, -1.0):
                best_by_symbol[symbol] = score
        if not best_by_symbol:
            return None
        ranked = sorted(best_by_symbol.items(), key=lambda kv: kv[1], reverse=True)
        top_sym, top_score = ranked[0]
        second = ranked[1][1] if len(ranked) > 1 else 0.0
        if top_score >= self.threshold and (top_score - second) >= self.margin:
            return Resolution(top_sym, top_score, "fuzzy", self._name_by_symbol.get(top_sym))
        return None

    def resolve(self, text: str) -> Resolution | None:
        """Best-effort resolution, or None when ambiguous / unknown / low-confidence."""
        if not text or not text.strip():
            return None
        return self._exact_token(text) or self._alias(text) or self._fuzzy(text)
