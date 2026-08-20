# Niveshak

Manipulation-risk scoring for Indian stock tips. Forward a tip from Telegram, WhatsApp,
YouTube or X and get a calibrated 0-100 risk score with the evidence behind it.

Built for Prasunethon 2.0 Hackathon 2026.

> Niveshak does not give investment advice. It evaluates whether a message shows the
> behavioural signature of a coordinated pump, and shows you why. Every decision remains
> yours.

## Getting started

```bash
uv sync --extra dev
uv run pytest
```

## Run it

Score a tip from the CLI:

```bash
PYTHONPATH=src python -m niveshak score "SUZLON sure shot! operator support, target 80 intraday, buy now pakka profit"
```

Run the API (POST /score, GET /health, POST /telegram/webhook):

```bash
PYTHONPATH=src uvicorn niveshak.api.app:app --reload
# curl -X POST localhost:8000/score -H 'content-type: application/json' -d '{"text":"..."}'
```

Run the Telegram bot locally (no public URL needed — responds to real messages):

```bash
TELEGRAM_BOT_TOKEN=<from @BotFather> PYTHONPATH=src python scripts/run_telegram_polling.py
```

## Deploy

The API is a stateless FastAPI app. `data/` (DuckDB store) and `models/` (model artifact)
are gitignored; a bare box therefore serves **message-only** scores and upgrades to full
scoring once those are present (ship them in the image or mount a volume).

**Railway (from GitHub, no CLI):** New Project → Deploy from GitHub → this repo. Railway uses
the `Dockerfile`. Set env: `TELEGRAM_BOT_TOKEN`, optional `TELEGRAM_WEBHOOK_SECRET`,
`RATE_LIMIT_PER_MIN`. After it's live at `https://<app>.up.railway.app`, point Telegram at it:

```bash
TELEGRAM_BOT_TOKEN=... python scripts/set_telegram_webhook.py https://<app>.up.railway.app/telegram/webhook
```

**Fly.io:** `flyctl launch` (detects the Dockerfile) → `flyctl secrets set TELEGRAM_BOT_TOKEN=...`
→ `flyctl deploy`, then run the same set-webhook command against the Fly URL.

Operational: per-IP rate limiting (429 with a clean body), one JSON log line per request, and
a catch-all that never returns a traceback to the caller.

## Documentation

- `CLAUDE.md` - project context, conventions, non-negotiable rules
- `docs/SPEC.md` - technical specification
- `docs/BUILD_PLAN.md` - sequenced milestones with acceptance criteria
- `docs/DATA_SOURCES.md` - where every dataset comes from and its licence

## Status

Pre-M0.
