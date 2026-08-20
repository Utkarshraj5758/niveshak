# Data sources

Every source here is public. Nothing behind a login, nothing personal, nothing paid.
If you add a source, add a row and state its licence and its access constraints.

| Source | What it gives | Access | Notes |
|---|---|---|---|
| NSE bhavcopy archives | Daily OHLC, volume, delivery % | Public ZIP archive | Non-browser user agents are blocked on some endpoints; prefer archive ZIPs over the quote API |
| BSE bhavcopy | Same, for BSE-listed and SME scrips | Public ZIP archive | Needed for SME coverage |
| NSE/BSE symbol master | Ticker to company mapping, listing dates | Public CSV | Refresh weekly; symbols get renamed |
| SEBI orders (interim, adjudication) | Confirmed manipulation events with scrips, dates, handles | Public PDFs on sebi.gov.in | Strong labels. Parse with PyMuPDF. Always store the source URL alongside every extracted fact |
| SEBI press releases and studies | Aggregate loss statistics for context | Public | Used in the pitch, not in the model |
| Public Telegram channels | Historical tips with timestamps | Telethon, public channels only | Never join private groups |
| Public YouTube videos | Tips in audio form | yt-dlp + Whisper | Transcription quality on Hinglish is mediocre; treat as lower-confidence input |
| Registered intermediary lists | Whether a handle belongs to a registered RA/IA | Public SEBI registers | Feeds the disclosure rule overlay |

## Rules

- Store the retrieval URL and timestamp for every record. Provenance is a product feature,
  not bookkeeping.
- Cache aggressively. Re-scraping the same bhavcopy is wasted time and unnecessary load.
- Never store end-user WhatsApp message content beyond what is needed to reply and for a
  short retention window. Document the window in the privacy notice before launch.
