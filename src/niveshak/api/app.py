"""Niveshak HTTP API + Telegram webhook.

Endpoints:
  GET  /health             liveness + what data/model is loaded
  POST /score              {text, source?} -> RiskScore
  POST /telegram/webhook   Telegram update -> scores and replies

Operational guarantees the brief asks for:
  * Rate limiting — a per-IP fixed-window limiter (429 with a clean JSON body).
  * Structured logs — one JSON line per request (method, path, status, ms, request_id).
  * No raw tracebacks to the user — a catch-all handler logs the traceback server-side and
    returns a generic JSON error with the request_id for correlation.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import uuid
from collections import defaultdict

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from niveshak.api import telegram
from niveshak.api.schemas import ScoreRequest, ScoreResponse
from niveshak.api.service import get_scorer, scorer_status

# --- structured logging to stdout (captured by Railway/Fly) ------------------------
_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(logging.Formatter("%(message)s"))
log = logging.getLogger("niveshak.api")
if not log.handlers:
    log.addHandler(_handler)
log.setLevel(logging.INFO)


def _jlog(**fields: object) -> None:
    log.info(json.dumps(fields, default=str))


RATE_LIMIT_PER_MIN = int(os.environ.get("RATE_LIMIT_PER_MIN", "30"))
_WINDOW = 60.0
_hits: dict[str, list[float]] = defaultdict(list)

app = FastAPI(title="Niveshak", version="0.1.0",
              description="Manipulation-risk scoring for stock tips.")


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@app.middleware("http")
async def rate_limit_and_log(request: Request, call_next):  # type: ignore[no-untyped-def]
    request_id = uuid.uuid4().hex[:12]
    request.state.request_id = request_id
    started = time.perf_counter()
    ip = _client_ip(request)

    # Fixed-window rate limit (health checks exempt).
    if request.url.path not in ("/health", "/"):
        now = time.time()
        recent = [t for t in _hits[ip] if now - t < _WINDOW]
        if len(recent) >= RATE_LIMIT_PER_MIN:
            _jlog(event="rate_limited", request_id=request_id, ip=ip, path=request.url.path)
            return JSONResponse(
                status_code=429,
                content={"error": "rate_limited",
                         "detail": f"Max {RATE_LIMIT_PER_MIN} requests/min. Slow down.",
                         "request_id": request_id},
                headers={"Retry-After": "60"},
            )
        recent.append(now)
        _hits[ip] = recent

    try:
        response = await call_next(request)
    except Exception:  # noqa: BLE001 - never leak a traceback to the client
        log.exception("unhandled_error request_id=%s", request_id)
        _jlog(event="request", request_id=request_id, method=request.method,
              path=request.url.path, status=500, ms=round((time.perf_counter() - started) * 1000, 1))
        return JSONResponse(
            status_code=500,
            content={"error": "internal_error",
                     "detail": "Something went wrong. Please try again.",
                     "request_id": request_id},
        )
    _jlog(event="request", request_id=request_id, method=request.method, path=request.url.path,
          status=response.status_code, ms=round((time.perf_counter() - started) * 1000, 1))
    return response


@app.get("/health")
def health() -> dict[str, object]:
    return {"status": "ok", **scorer_status()}


@app.post("/score", response_model=ScoreResponse)
def score(req: ScoreRequest, request: Request) -> ScoreResponse:
    rs = get_scorer().score_text(req.text, source=req.source)
    _jlog(event="scored", request_id=getattr(request.state, "request_id", None),
          ticker=rs.ticker, value=rs.value, band=rs.band, source=req.source)
    return rs


@app.post("/telegram/webhook")
async def telegram_webhook(request: Request) -> dict[str, str]:
    # Optional shared-secret check (set via setWebhook secret_token).
    secret = os.environ.get("TELEGRAM_WEBHOOK_SECRET")
    if secret and request.headers.get("x-telegram-bot-api-secret-token") != secret:
        return JSONResponse(status_code=403, content={"error": "forbidden"})  # type: ignore[return-value]

    update = await request.json()
    parsed = telegram.extract_message(update)
    if parsed is None:
        return {"ok": "ignored"}
    chat_id, text = parsed
    if text.strip().lower() in ("/start", "/help"):
        await telegram.send_message(chat_id, telegram.WELCOME)
        return {"ok": "welcomed"}
    rs = get_scorer().score_text(text, source="telegram")
    await telegram.send_message(chat_id, telegram.format_reply(rs))
    _jlog(event="telegram_scored", chat_id=chat_id, ticker=rs.ticker, value=rs.value, band=rs.band)
    return {"ok": "scored"}
