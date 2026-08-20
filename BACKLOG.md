# Backlog

Deliberately deferred work. Round 2 scope is frozen (SPEC §2); items land here instead of
expanding it. Each entry states why it's safe to defer and what would trip over it.

## Symbol-history mapping (point-in-time ticker resolution)

**Problem.** The ticker resolver (`src/niveshak/parse/tickers.py`) maps free text to the
**current** NSE symbol master: "Tata Motors" → `TMCV`, "Zomato" → `ETERNAL`. But historical
bhavcopy in `daily_prices` uses the symbol that was **live on each trade date**:
`TATAMOTORS`, `ZOMATO`, etc. The two namespaces do not line up across renames, demergers,
and delistings.

**Do not** build any historical-tip backtest that joins resolver output directly to
historical `daily_prices` rows. It would silently miss or mis-join every renamed/demerged
scrip (TATAMOTORS↔TMCV, ZOMATO↔ETERNAL, and many SME cases), quietly biasing any evaluation.

**Why it doesn't block Round 2.** The live Telegram demo scores **current** tips against
**current** data — resolver symbol and latest bhavcopy symbol are the same "now", so the
join is valid. The mismatch only appears if we backtest historical tips.

**Fix when needed (Phase 2).** Build a symbol-history table `(symbol_current, symbol_asof,
valid_from, valid_to, change_type)` from NSE symbol-change / name-change circulars (and ISIN
continuity, which survives most renames). Resolve a tip to the *current* symbol, then map to
the *as-of-tip-date* symbol before joining historical prices. ISIN is the most reliable join
key across renames and should be carried on both `symbols` and `daily_prices`.

---

## Other deferred items (from BUILD_PLAN "What was cut")

- MuRIL / IndicBERT fine-tuning for the parser (rule parser is the v1 baseline + weak-label
  generator).
- SEBI order corpus as strong labels (outcome-rule weak labels for now).
- Louvain community detection (burst detection carries the coordination signal).
- WhatsApp bot (needs Meta business verification — Telegram first).
- Browser extension (out of scope).
- SHAP (rule contributions are directly explainable; model-half importances reported offline).
- Swap sklearn HistGradientBoosting back to LightGBM once the host's OpenMP/VC++ runtime is
  fixed (LightGBM's native lib currently segfaults on any fit).
