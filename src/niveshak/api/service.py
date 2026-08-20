"""Lazily-built, resilient Scorer singleton for the API and bot.

Deploy reality: the DuckDB store and model artifact live under data/ and models/ (both
gitignored), so a fresh deploy box may not have them. Rather than crash, the service
degrades gracefully — a Scorer with no model/DB still parses the message and runs the
red-flag half, returning a valid (message-only) score. That is exactly the "bare but real"
endpoint we want live first; it upgrades to full scoring the moment data is present.
"""

from __future__ import annotations

import logging

from niveshak.score.assemble import Scorer

log = logging.getLogger("niveshak.api")

_scorer: Scorer | None = None


def get_scorer() -> Scorer:
    """Return a process-wide Scorer, building it once. Never raises."""
    global _scorer
    if _scorer is not None:
        return _scorer
    try:
        _scorer = Scorer.from_paths()
        log.info(
            "scorer_ready model=%s symbols=%s",
            _scorer.model is not None,
            _scorer.resolver is not None and len(getattr(_scorer.resolver, "_symbols", [])),
        )
    except Exception:  # noqa: BLE001 - degrade, don't crash the service
        log.exception("scorer_init_failed_degrading_to_message_only")
        _scorer = Scorer(con=None, model=None, resolver=None)
    return _scorer


def scorer_status() -> dict[str, object]:
    s = get_scorer()
    return {
        "model_loaded": s.model is not None,
        "symbols_loaded": bool(s.resolver and len(getattr(s.resolver, "_symbols", []))),
        "market_data": s.con is not None,
    }
