"""API tests: health, score contract, validation, rate limiting, and no-traceback errors.

The scorer is stubbed so these test the HTTP layer (limits, logging, error handling, schema)
independently of the heavy model — the pipeline itself is covered by the other suites.
"""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from niveshak.api import app as app_module
from niveshak.parse.tip import Tip
from niveshak.score.assemble import build_risk_score


class _FakeScorer:
    def score_text(self, text: str, *, source: str = "manual"):
        tip = Tip(tip_id="x", source=source, raw_text=text, language="en", direction="unclear",
                  urgency="high", guarantee_claim=True, insider_claim=True,
                  disclosure_present=False, ticker=None,
                  posted_at=datetime(2026, 8, 20, tzinfo=timezone.utc))
        return build_risk_score(tip, 0.0, None)


@pytest.fixture(autouse=True)
def _stub_scorer(monkeypatch):
    monkeypatch.setattr(app_module, "get_scorer", lambda: _FakeScorer())
    monkeypatch.setattr(app_module, "scorer_status",
                        lambda: {"model_loaded": True, "symbols_loaded": True, "market_data": True})
    app_module._hits.clear()


@pytest.fixture
def client():
    return TestClient(app_module.app)


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_score_ok(client):
    r = client.post("/score", json={"text": "sure shot pakka profit, operator news, buy now"})
    assert r.status_code == 200
    body = r.json()
    assert 0 <= body["value"] <= 100
    assert body["band"] in ("low", "elevated", "high")
    assert "not investment advice" in body["disclaimer"].lower()


def test_score_rejects_empty_text(client):
    assert client.post("/score", json={"text": ""}).status_code == 422


def test_rate_limit_returns_429(client, monkeypatch):
    monkeypatch.setattr(app_module, "RATE_LIMIT_PER_MIN", 3)
    app_module._hits.clear()
    codes = [client.post("/score", json={"text": "buy now pakka"}).status_code for _ in range(5)]
    assert codes.count(200) == 3
    assert codes[-1] == 429
    assert client.post("/score", json={"text": "x"}).json()["error"] == "rate_limited"


def test_no_traceback_leaks_on_error(client, monkeypatch):
    def boom():
        raise RuntimeError("db exploded with secret path C:/secret")
    monkeypatch.setattr(app_module, "get_scorer", boom)
    r = client.post("/score", json={"text": "hello"})
    assert r.status_code == 500
    body = r.json()
    assert body["error"] == "internal_error"
    assert "request_id" in body
    assert "Traceback" not in r.text and "secret" not in r.text


def test_telegram_webhook_ignores_non_message(client):
    r = client.post("/telegram/webhook", json={"update_id": 1})
    assert r.status_code == 200
    assert r.json()["ok"] == "ignored"
