# Niveshak API + Telegram webhook.
# Bundles the source only. The DuckDB store and model artifact (data/, models/) are
# gitignored and NOT baked in — a bare box serves message-only scores and upgrades to full
# scoring once those are mounted/shipped. See README "Deploy".
FROM python:3.12-slim

WORKDIR /app

COPY requirements-deploy.txt .
RUN pip install --no-cache-dir -r requirements-deploy.txt

COPY src/ ./src/
# Committed deploy store (trimmed DuckDB + model artifact) -> full scoring on a bare box.
COPY deploy/ ./deploy/

ENV PYTHONPATH=/app/src
ENV PORT=8000
EXPOSE 8000

# Railway/Fly inject $PORT; default to 8000 locally.
CMD ["sh", "-c", "uvicorn niveshak.api.app:app --host 0.0.0.0 --port ${PORT}"]
