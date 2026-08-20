"""Tests for the rule parser — one per extractor, plus a full realistic parse.

Hand-written tip strings (Hinglish + English + emoji), matching how tips actually arrive.
"""

import sys
from datetime import datetime, timezone

import pytest

from niveshak.parse import parser as P
from niveshak.parse.tickers import TickerResolver

sys.path.insert(0, "tests")
from test_ticker_resolution import MASTER  # reuse the grounded symbol fixture  # noqa: E402


@pytest.fixture(scope="module")
def lex():
    return P.load_lexicons()


@pytest.fixture(scope="module")
def resolver() -> TickerResolver:
    return TickerResolver.from_records(MASTER)


def test_detect_language():
    assert P.detect_language("Kal RELIANCE me tezi aayegi") == "mixed"
    assert P.detect_language("pakka lelo bhai turant") == "hi-Latn"
    assert P.detect_language("strong breakout expected today") == "en"


def test_detect_direction(lex):
    assert P.detect_direction("buy karo abhi", lex) == "long"
    assert P.detect_direction("bech do turant", lex) == "short"
    assert P.detect_direction("reliance ka result aaya", lex) == "unclear"


def test_extract_target_price():
    assert P.extract_target_price("SUZLON ka target 80, pakka") == 80.0
    assert P.extract_target_price("tgt: 1500 in 2 weeks") == 1500.0
    assert P.extract_target_price("target rs 45.5") == 45.5
    assert P.extract_target_price("no target mentioned here") is None
    # a bare number without a target keyword must NOT be read as a target
    assert P.extract_target_price("stock at 250 levels looking good") is None


def test_extract_horizon_days(lex):
    assert P.extract_horizon_days("intraday call book fast", lex) == 1
    assert P.extract_horizon_days("hold for 5 days", lex) == 5
    assert P.extract_horizon_days("target in 2 weeks", lex) == 14
    assert P.extract_horizon_days("1 month view", lex) == 30
    assert P.extract_horizon_days("long term invest karo", lex) is None
    assert P.extract_horizon_days("positional trade", lex) == 5


def test_detect_urgency(lex):
    assert P.detect_urgency("buy now 🚀🚀", lex) == "high"
    assert P.detect_urgency("accumulate today slowly", lex) == "medium"
    assert P.detect_urgency("decent long term company", lex) == "low"


def test_has_guarantee_claim(lex):
    assert P.has_guarantee_claim("sure shot profit", lex) is True
    assert P.has_guarantee_claim("100% guaranteed returns", lex) is True
    assert P.has_guarantee_claim("looks reasonable", lex) is False


def test_has_insider_claim(lex):
    assert P.has_insider_claim("operator support confirmed", lex) is True
    assert P.has_insider_claim("insider news aaya hai", lex) is True
    assert P.has_insider_claim("read the public results", lex) is False


def test_has_disclosure(lex):
    assert P.has_disclosure("SEBI registered research analyst, risk disclosure applies", lex) is True
    assert P.has_disclosure("just forwarding a tip", lex) is False


def test_full_parse_realistic_scam_tip(resolver):
    text = "🚀 SUZLON sure shot! operator support, target 80 intraday. buy now, pakka profit 🔥"
    when = datetime(2026, 8, 20, tzinfo=timezone.utc)
    tip = P.parse_message(text, source="telegram", channel_id="c123",
                          posted_at=when, resolver=resolver)
    assert tip.ticker == "SUZLON"
    assert tip.direction == "long"
    assert tip.target_price == 80.0
    assert tip.horizon_days == 1
    assert tip.urgency == "high"
    assert tip.guarantee_claim is True
    assert tip.insider_claim is True
    assert tip.disclosure_present is False
    assert tip.source == "telegram"
    assert tip.posted_at == when
    assert tip.tip_id                        # auto-generated


def test_full_parse_clean_disclosed_tip(resolver):
    text = "INFY looks strong for delivery. SEBI registered RA, risk disclosure applies."
    tip = P.parse_message(text, resolver=resolver)
    assert tip.ticker == "INFY"
    assert tip.disclosure_present is True
    assert tip.guarantee_claim is False
    assert tip.insider_claim is False
    assert tip.urgency == "low"


def test_parse_without_resolver_leaves_ticker_none():
    tip = P.parse_message("some random market chatter", source="manual")
    assert tip.ticker is None
