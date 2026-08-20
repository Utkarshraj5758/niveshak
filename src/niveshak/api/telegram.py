"""Telegram glue: format a RiskScore reply, talk to the Bot API, and handle updates.

Kept transport-light: a couple of httpx calls, no telegram SDK. Works both as a webhook
handler (production) and from the polling script (local, no public URL needed).
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from niveshak.score.assemble import RiskScore

log = logging.getLogger("niveshak.api")

_API = "https://api.telegram.org/bot{token}/{method}"
_BAND_TAG = {"low": "🟢 LOW", "elevated": "🟠 ELEVATED", "high": "🔴 HIGH"}

WELCOME = (
    "Namaste! I'm Niveshak. Forward me a stock tip (Telegram/WhatsApp/YouTube text) and "
    "I'll rate its *manipulation risk* 0–100 with reasons.\n\n"
    "I judge the message, not the stock — I never give buy/sell advice."
)


def bot_token() -> str | None:
    return os.environ.get("TELEGRAM_BOT_TOKEN")


def format_reply(rs: RiskScore) -> str:
    """Plain-text Telegram reply. Message-level reasons only; ends with the disclaimer."""
    lines = [
        f"*Manipulation risk: {rs.value}/100*  {_BAND_TAG.get(rs.band, rs.band.upper())}",
        f"Ticker: {rs.ticker or '—'}  ·  confidence {rs.confidence:.0%}",
    ]
    if rs.contributions:
        lines.append("")
        lines.append("Why:")
        lines.extend(f"• {c.reason}" for c in rs.contributions)
    for n in rs.notes:
        lines.append(f"_({n})_")
    lines.append("")
    lines.append(f"_{rs.disclaimer}_")
    return "\n".join(lines)


def extract_message(update: dict[str, Any]) -> tuple[int, str] | None:
    """Pull (chat_id, text) from a Telegram update, or None if there's nothing to score."""
    msg = update.get("message") or update.get("edited_message")
    if not msg:
        return None
    chat = msg.get("chat", {})
    chat_id = chat.get("id")
    text = msg.get("text")
    if chat_id is None or not text:
        return None
    return int(chat_id), str(text)


async def send_message(chat_id: int, text: str, *, token: str | None = None) -> None:
    token = token or bot_token()
    if not token:
        log.warning("telegram_send_skipped_no_token chat_id=%s", chat_id)
        return
    url = _API.format(token=token, method="sendMessage")
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown",
               "disable_web_page_preview": True}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(url, json=payload)
            if r.status_code != 200:
                log.warning("telegram_send_failed status=%s body=%s", r.status_code, r.text[:200])
    except httpx.HTTPError:
        log.exception("telegram_send_error chat_id=%s", chat_id)


def set_webhook(token: str, url: str, *, secret: str | None = None) -> dict[str, Any]:
    """One-shot helper to register the webhook (used by scripts/set_telegram_webhook.py)."""
    api = _API.format(token=token, method="setWebhook")
    payload: dict[str, Any] = {"url": url, "allowed_updates": ["message"]}
    if secret:
        payload["secret_token"] = secret
    resp = httpx.post(api, json=payload, timeout=15)
    resp.raise_for_status()
    return resp.json()
