"""Register the Telegram webhook against a deployed URL.

    TELEGRAM_BOT_TOKEN=... python scripts/set_telegram_webhook.py https://<app>/telegram/webhook

Optionally set TELEGRAM_WEBHOOK_SECRET to also require the shared-secret header.
"""

from __future__ import annotations

import os
import sys

from niveshak.api import telegram


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print("Set TELEGRAM_BOT_TOKEN first.")
        return 2
    url = sys.argv[1]
    secret = os.environ.get("TELEGRAM_WEBHOOK_SECRET")
    result = telegram.set_webhook(token, url, secret=secret)
    print(result)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
