# Niveshak — project context for Claude Code

## What this is

Niveshak scores an individual **stock tip** for pump-and-dump manipulation risk. A user
forwards a message (Telegram / WhatsApp / YouTube / X) and gets back a calibrated
**0–100 Manipulation Risk Score** plus the specific evidence that produced it.

Built for Prasunethon 2.0 Hackathon 2026 (Round 2 = production-level deployed project).
Solo build, **4-day timeline**. Prefer working over elegant. Read `docs/BUILD_PLAN.md`
before proposing any work — it defines what is in scope and what has been deliberately cut.

Delivery surface is a **Telegram bot**, not WhatsApp: WhatsApp Cloud API needs Meta business
verification, which cannot be completed inside the timeline.

## Non-negotiable product rules

These are not style preferences. Violating them breaks the product's legal and ethical footing.

1. **Never emit buy/sell/hold advice.** No price targets, no "this stock will go up", no
   portfolio suggestions. The output is a manipulation-risk judgement about a *message*,
   not a view on a *security*. This keeps us outside SEBI investment-adviser registration.
2. **Never name or accuse individuals.** Score channels, handles and scrips as behavioural
   patterns. Any person-level claim must come from a cited public SEBI order, quoted as
   "SEBI's order alleges…", never as our own finding.
3. **Never present a score as certainty.** Every score ships with a confidence band and the
   top contributing features. Binary "SCAM / SAFE" labels are forbidden in the UI.
4. **Public data only.** No login-walled scraping, no private groups, no personal data of
   end users beyond what is needed to reply to them.
5. **Every score must be explainable.** If a feature can't be rendered as a human-readable
   reason, it doesn't go in the model.

## Repo layout

```
src/niveshak/
  ingest/    # Telegram, YouTube, X, WhatsApp inbound; ASR; OCR
  parse/     # Hinglish tip -> structured Tip object
  market/    # NSE/BSE bhavcopy, feature store, microstructure features
  graph/     # channel<->ticker bipartite graph, coordination detection
  score/     # feature assembly, LightGBM model, calibration, rule overlays
  explain/   # SHAP -> plain-language Hindi/English reasons
  api/       # FastAPI app, WhatsApp webhook, dashboard endpoints
docs/        # SPEC.md, BUILD_PLAN.md, DATA_SOURCES.md — read these before big changes
data/        # gitignored; raw + processed datasets live here
scripts/     # one-off ETL and training entrypoints
tests/
```

## Core data contract

The `Tip` object is the spine of the system. Everything upstream produces it, everything
downstream consumes it. Do not change its shape without updating `docs/SPEC.md`.

```python
Tip(
    tip_id: str,
    source: Literal["telegram", "youtube", "x", "whatsapp", "manual"],
    channel_id: str | None,
    raw_text: str,
    language: str,            # "hi-Latn", "en", "mixed"
    ticker: str | None,       # resolved NSE/BSE symbol
    direction: Literal["long", "short", "unclear"],
    target_price: float | None,
    horizon_days: int | None,
    urgency: Literal["low", "medium", "high"],
    guarantee_claim: bool,    # "pakka", "sure shot", "guaranteed"
    insider_claim: bool,      # "operator support", "insider news"
    disclosure_present: bool, # SEBI-mandated disclosure in the message
    posted_at: datetime,
)
```

## Conventions

- Python 3.11+. `uv` for dependency management. Type hints everywhere; `mypy --strict` on
  `src/niveshak/score` and `src/niveshak/parse` at minimum.
- Pydantic v2 for all data contracts. No bare dicts crossing module boundaries.
- DuckDB for the feature store and all analytical queries. Postgres only for app state.
- Every model artifact is versioned and written with the feature list it was trained on.
  A score produced by an unknown feature set is a bug, not a fallback.
- Tests: pytest. Every scoring rule needs a test with a hand-written example tip.
- No notebook code in `src/`. Notebooks are for exploration only.

## Things that will waste your time (learned constraints)

- NSE blocks non-browser user agents on some endpoints — set headers and expect to need a
  session cookie warm-up. Prefer archived bhavcopy ZIPs over the live quote API.
- Ticker resolution from free text is the #1 source of silent errors. "RELIANCE" vs
  "RELIANCE POWER" vs "RPOWER" are different companies. Always resolve against the official
  NSE/BSE symbol master, fuzzy-match with a confidence threshold, and mark
  `ticker=None` rather than guessing.
- Hinglish tokenization: do not lowercase blindly, and do not strip emoji — 🚀 and 🔥 are
  real features in this domain.
- SME scrips have different circuit rules and much thinner data than mainboard. Keep an
  `is_sme` flag on every market feature row; models that ignore it will overfit to mainboard.

## Scoring architecture (4-day scope)

The score has two halves, deliberately, because there is no labelled Hinglish tip corpus
and no time to build one:

```
final_score = 0.6 * scrip_susceptibility_model + 0.4 * message_red_flag_rules
```

- **Scrip susceptibility**: LightGBM trained on bhavcopy market features alone, weakly
  labelled by the outcome rule (run-up then collapse). Needs no text labels, so it is
  genuinely trainable and evaluable in the time available.
- **Message red flags**: transparent weighted rules over the parsed tip. Each flag carries
  a fixed documented weight and its own reason string.

The 0.6/0.4 split is a documented product decision, not a fitted parameter. Do not present
it as one.

## Definition of done

A publicly reachable Telegram bot and a single-page web dashboard that score real tips
against real NSE data, plus source code, documentation, a deployed URL, a demo video, and
an evaluation report containing a real PR-AUC number. Not a mockup.
