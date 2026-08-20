# Build plan — 4 days

Assumes ~10–12 focused hours per day. Solo.

This is not the six-week plan compressed. It is a smaller product that is demoable end to
end. Read "What was cut" before starting, so you know what you are choosing to give up.

## The two structural changes

1. **Telegram bot, not WhatsApp.** WhatsApp Cloud API requires Meta business verification
   for production messaging. That review takes days and cannot be accelerated. Telegram
   BotFather issues a token instantly.
2. **Two-part score.** A trained model on market data only (needs no text labels) plus a
   transparent rule scorer on the message. This gets real, evaluated ML inside four days.

```
final_score = 0.6 * scrip_susceptibility_model + 0.4 * message_red_flag_rules
```

Those weights are a documented product decision, not a fitted parameter. Say so out loud.

---

## Day 1 — Market data and the trained model

**Morning (4h) — data in**
- Bhavcopy downloader, 2 years, local cache. Start this running in the first thirty
  minutes; it is slow and everything depends on it.
- NSE + BSE symbol master loader.
- DuckDB tables: `daily_prices`, `symbols`.

**Afternoon (4h) — features**
- Per `(ticker, date)`: 5/10/20d run-up, volume z-score vs 60d mean, delivery % and its
  trend, upper-circuit count over trailing 10 sessions, market-cap bucket, `is_sme`,
  days since listing.
- One function per feature, one test per function. No exceptions — there is no time on
  day 3 to debug a silently wrong feature.

**Evening (3h) — labels and model**
- Outcome-rule labeller: positive if +25% within 30 sessions, then −30% from that peak
  within the next 30. Forward-looking, so training only — never a feature.
- LightGBM, temporal split (train earlier, test later — never random).
- Calibrate with isotonic regression. Save the artifact with its feature manifest.
- Write results to `reports/model_v1.md`.

**Gate:** you have a PR-AUC number and a calibration curve. If PR-AUC is at or below the
base rate, stop and hunt for leakage before continuing.

---

## Day 2 — Parsing and scoring

**Morning (4h) — ticker resolution**
- rapidfuzz over the symbol master, confidence threshold, returns `None` below it.
- Hand-build 60 test cases from real tip strings, including hard negatives (RELIANCE vs
  RELIANCE POWER, nicknames, partial names, ambiguous abbreviations).
- Highest-risk silent failure in the system. Do not shortcut it.

**Afternoon (4h) — rule parser and red-flag scorer**
- Regex + YAML lexicons for direction, target price, horizon, urgency, guarantee language
  ("pakka", "sure shot", "confirm"), insider language ("operator", "insider news"), and
  disclosure presence. Keep emoji — 🚀 and 🔥 are real signal in this domain.
- Red-flag scorer: each flag contributes a fixed documented weight and its own
  human-readable reason string.

**Evening (3h) — combine and explain**
- Assemble the final score, band it (low / elevated / high), attach top 3 contributions.
- Template-rendered reasons in English. Hindi templates only if time is left over.
- Skip SHAP. Rule contributions are already explainable, and the model half has few enough
  features to report permutation importance offline.

**Gate:** `niveshak score "<paste a real tip>"` prints a score, a band, and three reasons.

---

## Day 3 — Bot, API, and coordination

**Morning (4h) — API and bot**
- FastAPI `POST /score`, raw text in, score object out.
- Telegram bot wired to it. Rate limiting, structured logs, and never a raw traceback back
  to the user.
- **Deploy today, not on day 4.** Railway or Fly. Deployment always breaks; find out now.

**Afternoon (4h) — coordination detection (the differentiator)**
- Telethon backfill of 8–12 public tip channels, last 90 days only. A few thousand
  messages is plenty to demonstrate the mechanism.
- Burst feature: distinct channels mentioning a ticker within 48h vs that ticker's baseline.
- Feed it into the red-flag half as one more weighted contribution.
- Skip Louvain communities. Burst detection alone carries the demo.

**Evening (3h) — buffer**
Schedule nothing here. Day 1 or 2 will overrun and this is where it goes. If nothing
overran, harden error handling and test the score-combination logic.

**Gate:** you send a tip from your phone to the bot and get a scored reply with reasons.

---

## Day 4 — Surface, evidence, submission

**Morning (4h) — minimal dashboard**
- One page, mobile-first, tested at 360px width: paste a tip, see the score, see the
  evidence breakdown, see the Pump Watchlist (current high-burst tickers).
- Next.js if you are fluent in it. If not, a single FastAPI-served HTML page with Tailwind
  from CDN. A working plain page beats a broken framework app.

**Afternoon (3h) — demo video**
- Under 3 minutes: real tip in, real score out, evidence shown, then the watchlist.
- Record while everything works. Do not leave this until after the docs.

**Evening (3h) — documentation and deck update**
- README a stranger can clone and run from.
- Architecture diagram.
- Replace the illustrative mention-curve chart in the deck with your real burst data, and
  put the actual PR-AUC on the impact slide.

---

## What was cut, and what to say about it

Judges respond better to "we scoped deliberately, here is the evaluation" than to a broad
system with nothing measured. Be direct about the cuts.

| Cut | Say this |
|---|---|
| MuRIL / IndicBERT fine-tuning | The rule parser is the v1 baseline and it generates the weak labels the fine-tune needs. Phase 2. |
| SEBI order corpus as strong labels | Outcome-rule weak labels for now. Strong labels are the next accuracy step and the pipeline is built to take them. |
| Louvain community detection | Burst detection captures the coordination signal; communities add attribution, which is Phase 3. |
| WhatsApp bot | Telegram first, because it is where the tips originate. WhatsApp needs Meta verification — a business timeline, not an engineering one. |
| Browser extension | Already out of scope. |
| SHAP | Rule contributions are directly explainable; model-half importances reported offline. |

## Never cut

- **Calibration.** An uncalibrated score is a number with no meaning.
- **The evaluation report.** One real PR-AUC number outweighs everything on the cut list.
- **The explanation strings.** A score with no reason is the black box you promised not to build.
- **The no-advice rule.** Four days of pressure is exactly when this gets violated. It stays.

## Honest risk assessment

The realistic failure mode is not running out of features. It is losing nine hours on day
one to NSE's blocking behaviour and never reaching the model.

- Start the bhavcopy download in the first thirty minutes, in the background.
- If NSE blocks you, fall back to a public NSE historical dataset for day 1 and swap the
  live fetcher in later. A stale dataset that trains a model beats a live fetcher that doesn't.
- Timebox every block. If one overruns by more than an hour, take the fallback and move on.
