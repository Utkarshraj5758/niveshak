# Niveshak — technical specification

## 1. Problem

Indian retail investors receive stock tips through Telegram, WhatsApp, YouTube and X. A
significant share of these are engineered: operators accumulate an illiquid microcap or
SME scrip, amplify it across coordinated channels, and sell into the retail buying they
created. SEBI enforcement confirms the pattern but arrives months later.

There is no tool that evaluates a *specific tip* at the *moment of decision*.

## 2. Scope

**In scope for Round 2**
- Ingestion from Telegram (public channels) and YouTube (public videos)
- WhatsApp inbound for user-submitted tips
- Hinglish + English tip parsing
- NSE equity cash-segment market features (mainboard + SME)
- Coordination detection across ingested channels
- LightGBM risk model with SHAP explanations
- WhatsApp bot + Next.js dashboard

**Explicitly out of scope for Round 2**
- Derivatives, commodities, crypto
- Regional languages beyond Hindi/English
- Real-time streaming (batch every 15 min is sufficient)
- Any auto-trading or brokerage integration

## 3. Pipeline

```
sources ──> ingest ──> parse ──> ┌─> market features ─┐
                                  ├─> channel features ┼─> score ──> explain ──> deliver
                                  └─> graph features  ─┘
```

### 3.1 Ingest
Normalises every inbound artifact into `RawMessage(source, channel_id, text, media_ref, posted_at)`.
- Telegram: Telethon, public channels only, historical backfill + polling
- YouTube: yt-dlp for audio, faster-whisper for transcription, chunked to ~60s segments
- Images/screenshots: Tesseract OCR, then treated as text
- WhatsApp: Cloud API webhook

### 3.2 Parse
`RawMessage -> Tip` (contract in CLAUDE.md).
- **v1 (rules)**: regex + symbol-master lookup for tickers, keyword lexicons for urgency,
  guarantee and insider claims. Ship this first — it is a usable baseline and it generates
  weak labels for v2.
- **v2 (model)**: MuRIL or IndicBERT fine-tuned for token classification (ticker, target,
  horizon) plus sequence classification (urgency, claim flags).
- Ticker resolution is a separate, testable component with its own accuracy metric.

### 3.3 Market features
Computed per `(ticker, date)` from NSE bhavcopy, stored in DuckDB.
- 5/10/20-day price run-up before the tip
- Volume z-score vs trailing 60-day mean
- Delivery percentage and its trend
- Count of upper-circuit closes in trailing 10 sessions
- Free float and market cap bucket
- `is_sme` flag
- Days since listing

### 3.4 Channel features
Per channel, computed from our own historical archive.
- Number of distinct tickers pushed in trailing 30 days
- Median forward 30-day return of past calls
- Share of past calls that met the pump pattern (see 3.6)
- Disclosure presence rate
- Account age and posting cadence

### 3.5 Graph features
Bipartite graph: channels ↔ tickers, edges weighted by mention count within a time window.
- Burst detection: count of distinct channels mentioning a ticker within 48h, vs that
  ticker's trailing baseline
- Louvain community detection over the channel projection; flag channels that repeatedly
  co-occur on the same low-liquidity scrips
- Feature output: `n_channels_48h`, `burst_z_score`, `community_id`, `community_risk`

### 3.6 Labels

Two label sources, combined:

**Strong labels — SEBI enforcement corpus.** Parse public interim and adjudication orders
(PyMuPDF) into `(scrip, entity, handle, date_range, order_url)`. Any tip about a named
scrip inside a named date range is a confirmed positive.

**Weak labels — outcome rule.** A tip is weakly positive if, from the tip date, the scrip
rises >25% within 30 sessions and then falls >30% from that peak within the following 30
sessions. Compute from bhavcopy history. Document the exact thresholds in code; they are
tunable hyperparameters, not constants.

Guard against leakage: the outcome rule uses forward returns, so it may only be used for
training labels, never as a model feature.

### 3.7 Score
LightGBM binary classifier over the assembled feature vector, probability calibrated
(isotonic or Platt) on a held-out set, mapped to 0–100.

Rule overlays applied *after* the model, each contributing a fixed bounded adjustment and
its own human-readable reason:
- No SEBI disclosure present and an explicit price target → +
- Guarantee or insider claim language → +
- SME scrip with <30 days since listing → +
- Registered research analyst with a disclosure → −

Output: `RiskScore(value: int, band: Literal["low","elevated","high"], confidence: float, contributions: list[Contribution])`

### 3.8 Explain
SHAP values on the model features, merged with rule-overlay reasons, ranked by absolute
contribution. Top 3 rendered as sentences from templates, then optionally rewritten by an
LLM for fluency in Hindi or English. **The LLM rewrites; it never decides.** If the LLM
call fails, fall back to the templates.

### 3.9 Deliver
- WhatsApp bot: forward a message → reply with score, band, top 3 reasons, disclaimer
- Dashboard: search, watchlist, channel leaderboard, per-tip evidence view
- Public Pump Watchlist: currently high-burst scrips, read-only

## 4. Evaluation

Report on a temporally held-out test set (train on earlier dates, test on later — never
random split, the graph features leak across time).
- Precision / recall / PR-AUC against strong labels
- Calibration curve (predicted vs observed positive rate)
- Ticker resolution accuracy, reported separately
- False-positive review: manually inspect the 20 highest-scoring true negatives

Target: precision above 0.7 at the "high" band. A noisy alarm is worse than no alarm.

## 5. Risks

| Risk | Mitigation |
|---|---|
| Labelled Hinglish data is scarce | Rule-based v1 generates weak labels; hand-label ~2,000 tips for fine-tuning |
| False positives destroy trust | Calibrated bands, confidence shown, evidence always visible, precision-weighted threshold |
| Legal / defamation exposure | Behaviour and scrip level only; person-level claims quoted from public orders with citation |
| Platform API access closes | Public sources only; degrade to market-signal-only scoring if a source disappears |
| Scope creep kills the deadline | Round 2 scope in §2 is frozen; anything else goes in a BACKLOG.md |
