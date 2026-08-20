"""Run the Telegram bot by long-polling — no public URL needed, for local/demo use.

    TELEGRAM_BOT_TOKEN=123:abc  PYTHONPATH=src  python scripts/run_telegram_polling.py

This lets the bot respond to real messages before the webhook deploy is live. In production
use the /telegram/webhook endpoint instead (scripts/set_telegram_webhook.py).
"""

from __future__ import annotations

import os
import time

import httpx

from niveshak.api import telegram
from niveshak.api.service import get_scorer

API = "https://api.telegram.org/bot{token}/{method}"


def main() -> int:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print("Set TELEGRAM_BOT_TOKEN (from @BotFather) first.")
        return 2
    scorer = get_scorer()
    print("niveshak bot polling… (Ctrl-C to stop)")
    offset = 0
    with httpx.Client(timeout=40) as client:
        while True:
            try:
                r = client.get(API.format(token=token, method="getUpdates"),
                               params={"timeout": 30, "offset": offset, "allowed_updates": '["message"]'})
                for upd in r.json().get("result", []):
                    offset = upd["update_id"] + 1
                    parsed = telegram.extract_message(upd)
                    if not parsed:
                        continue
                    chat_id, text = parsed
                    if text.strip().lower() in ("/start", "/help"):
                        reply = telegram.WELCOME
                    else:
                        reply = telegram.format_reply(scorer.score_text(text, source="telegram"))
                    client.post(API.format(token=token, method="sendMessage"),
                                json={"chat_id": chat_id, "text": reply, "parse_mode": "Markdown",
                                      "disable_web_page_preview": True})
                    print(f"replied to {chat_id}: {text[:60]!r}")
            except httpx.HTTPError as exc:
                print(f"poll error: {exc}; retrying in 3s")
                time.sleep(3)


if __name__ == "__main__":
    raise SystemExit(main())
