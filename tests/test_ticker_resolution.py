"""60-case ticker-resolution test set — written BEFORE the resolver (Day 2 morning).

Ticker resolution is the #1 source of silent errors in this system: a wrong ticker sends a
score about the wrong company, which is worse than returning nothing. So the bar is:
  * accuracy >= 0.90 across the 60 realistic cases, and
  * ZERO confident-wrong answers on the hard negatives — every ambiguous/unknown/stale case
    must return None, never a plausible-but-wrong symbol.

The cases are grounded in the real NSE master (verified against the loaded `symbols` table),
including the traps that actually exist today:
  * RELIANCE (Industries) vs RELIANCE POWER (RPOWER) vs RELIANCE COMMUNICATIONS (RCOM)
  * "Tata Motors" resolves to TMCV — the old TATAMOTORS ticker no longer exists (demerger)
  * "Zomato" is stale — the company is now ETERNAL — so bare "Zomato" must be None
  * "Bajaj" / "Adani" / "Mahindra" / "HDFC" / "Tata" are ambiguous families -> None

The master fixture below includes the ambiguity siblings so the resolver is forced to make
these calls, and the test is deterministic (no DB dependency).
"""

import pytest

from niveshak.parse.tickers import TickerResolver

# (symbol, company name) — a realistic slice of the NSE master incl. ambiguity siblings.
MASTER: list[tuple[str, str]] = [
    ("RELIANCE", "Reliance Industries Limited"),
    ("RPOWER", "Reliance Power Limited"),
    ("RCOM", "Reliance Communications Limited"),
    ("RELINFRA", "Reliance Infrastructure Limited"),
    ("RIIL", "Reliance Industrial Infrastructure Limited"),
    ("RELCHEMQ", "Reliance Chemotex Industries Limited"),
    ("RHFL", "Reliance Home Finance Limited"),
    ("SBIN", "State Bank of India"),
    ("SBICARD", "SBI Cards and Payment Services Limited"),
    ("SBILIFE", "SBI Life Insurance Company Limited"),
    ("HDFCBANK", "HDFC Bank Limited"),
    ("HDFCLIFE", "HDFC Life Insurance Company Limited"),
    ("HDFCAMC", "HDFC Asset Management Company Limited"),
    ("INFY", "Infosys Limited"),
    ("TCS", "Tata Consultancy Services Limited"),
    ("WIPRO", "Wipro Limited"),
    ("MARUTI", "Maruti Suzuki India Limited"),
    ("JAYBARMARU", "Jay Bharat Maruti Limited"),
    ("TATASTEEL", "Tata Steel Limited"),
    ("TMCV", "Tata Motors Limited"),
    ("TMPV", "Tata Motors Passenger Vehicles Limited"),
    ("TATAPOWER", "Tata Power Company Limited"),
    ("TATACHEM", "Tata Chemicals Limited"),
    ("BAJFINANCE", "Bajaj Finance Limited"),
    ("BAJAJFINSV", "Bajaj Finserv Limited"),
    ("BAJAJ-AUTO", "Bajaj Auto Limited"),
    ("BAJAJHLDNG", "Bajaj Holdings & Investment Limited"),
    ("HINDUNILVR", "Hindustan Unilever Limited"),
    ("ICICIBANK", "ICICI Bank Limited"),
    ("KOTAKBANK", "Kotak Mahindra Bank Limited"),
    ("LT", "Larsen & Toubro Limited"),
    ("M&M", "Mahindra & Mahindra Limited"),
    ("M&MFIN", "Mahindra & Mahindra Financial Services Limited"),
    ("MAHLIFE", "Mahindra Lifespace Developers Limited"),
    ("MAHEPC", "Mahindra EPC Irrigation Limited"),
    ("TITAN", "Titan Company Limited"),
    ("TRENT", "Trent Limited"),
    ("IDEA", "Vodafone Idea Limited"),
    ("IDEAFORGE", "Ideaforge Technology Limited"),
    ("LICI", "Life Insurance Corporation Of India"),
    ("DMART", "Avenue Supermarts Limited"),
    ("HAL", "Hindustan Aeronautics Limited"),
    ("BEL", "Bharat Electronics Limited"),
    ("IRCTC", "Indian Railway Catering And Tourism Corporation Limited"),
    ("IRFC", "Indian Railway Finance Corporation Limited"),
    ("IREDA", "Indian Renewable Energy Development Agency Limited"),
    ("NHPC", "NHPC Limited"),
    ("SUZLON", "Suzlon Energy Limited"),
    ("YESBANK", "Yes Bank Limited"),
    ("JPPOWER", "Jaiprakash Power Ventures Limited"),
    ("ITC", "ITC Limited"),
    ("ITCHOTELS", "ITC Hotels Limited"),
    ("ADANIENT", "Adani Enterprises Limited"),
    ("ADANIPOWER", "Adani Power Limited"),
    ("ADANIGREEN", "Adani Green Energy Limited"),
    ("ADANIPORTS", "Adani Ports and Special Economic Zone Limited"),
    ("ADANIENSOL", "Adani Energy Solutions Limited"),
    ("ATGL", "Adani Total Gas Limited"),
    ("ETERNAL", "ETERNAL LIMITED"),
    ("VEDL", "Vedanta Limited"),
    ("PAYTM", "One 97 Communications Limited"),
]

# (query as it might appear in a tip, expected symbol or None)
CASES: list[tuple[str, str | None]] = [
    # --- exact ticker mentions (tips usually write the symbol in caps) ---
    ("RELIANCE", "RELIANCE"),
    ("SBIN", "SBIN"),
    ("INFY", "INFY"),
    ("TCS", "TCS"),
    ("HAL", "HAL"),
    ("BEL", "BEL"),
    ("IRCTC", "IRCTC"),
    ("WIPRO", "WIPRO"),
    ("SUZLON", "SUZLON"),
    ("IREDA", "IREDA"),
    ("YESBANK", "YESBANK"),
    ("RPOWER", "RPOWER"),
    # --- symbol embedded in a realistic Hinglish/English tip ---
    ("Kal RELIANCE me bumper tezi aayegi 🚀", "RELIANCE"),
    ("SUZLON ka target 80, pakka", "SUZLON"),
    ("buy YESBANK today sure shot", "YESBANK"),
    ("IRCTC intraday call, book fast", "IRCTC"),
    ("NHPC lele bhai long term", "NHPC"),
    ("IRFC breakout coming 🔥", "IRFC"),
    ("load karo HAL defence multibagger", "HAL"),
    ("ITC accumulate zone", "ITC"),
    # --- company names, full or partial ---
    ("Reliance Industries", "RELIANCE"),
    ("Reliance Power", "RPOWER"),
    ("Reliance Communications", "RCOM"),
    ("State Bank of India", "SBIN"),
    ("HDFC Bank", "HDFCBANK"),
    ("Tata Consultancy Services", "TCS"),
    ("Maruti Suzuki", "MARUTI"),
    ("Tata Steel", "TATASTEEL"),
    ("Bajaj Finance", "BAJFINANCE"),
    ("Bajaj Finserv", "BAJAJFINSV"),
    ("Bajaj Auto", "BAJAJ-AUTO"),
    ("Hindustan Unilever", "HINDUNILVR"),
    ("ICICI Bank", "ICICIBANK"),
    ("Kotak Mahindra Bank", "KOTAKBANK"),
    ("Larsen & Toubro", "LT"),
    ("Mahindra & Mahindra", "M&M"),
    ("Titan Company", "TITAN"),
    ("Vodafone Idea", "IDEA"),
    ("Avenue Supermarts", "DMART"),
    ("Hindustan Aeronautics", "HAL"),
    # --- curated nicknames / abbreviations ---
    ("SBI", "SBIN"),
    ("Infy", "INFY"),
    ("HUL", "HINDUNILVR"),
    ("L&T", "LT"),
    ("DMart", "DMART"),
    ("Maruti", "MARUTI"),
    ("Tata Motors", "TMCV"),
    ("LIC", "LICI"),
    # --- HARD NEGATIVES: ambiguous families -> must be None ---
    ("Bajaj", None),
    ("Adani", None),
    ("Tata", None),
    ("HDFC", None),
    ("Mahindra", None),
    ("Reliance", None),        # bare word, ambiguous among Reliance* -> None (not RELIANCE)
    ("REL", None),             # ambiguous abbreviation
    ("Bank", None),            # generic
    # --- HARD NEGATIVES: stale / unknown / non-stock -> must be None ---
    ("TATAMOTORS", None),      # old ticker no longer exists (now TMCV) -> never guess
    ("Zomato", None),          # renamed to ETERNAL -> unknown alias -> None, not a wrong map
    ("target 500 book profit", None),
    ("sure shot pakka profit 🔥🚀", None),
]

# Cases that must NEVER return a wrong non-None symbol (None is the only safe answer).
HARD_NEGATIVES = [q for q, exp in CASES if exp is None]


@pytest.fixture(scope="module")
def resolver() -> TickerResolver:
    return TickerResolver.from_records(MASTER)


def test_case_count_is_60():
    assert len(CASES) == 60


def test_accuracy_at_least_90pct(resolver: TickerResolver):
    wrong: list[str] = []
    for query, expected in CASES:
        res = resolver.resolve(query)
        got = res.symbol if res else None
        if got != expected:
            wrong.append(f"{query!r}: expected {expected}, got {got}"
                         + (f" (score {res.score:.1f})" if res else ""))
    accuracy = 1 - len(wrong) / len(CASES)
    assert accuracy >= 0.90, f"accuracy {accuracy:.2%}\n" + "\n".join(wrong)


def test_zero_confident_wrong_on_hard_negatives(resolver: TickerResolver):
    """The non-negotiable: an ambiguous/unknown query may return None, never a wrong symbol."""
    offenders = []
    for query in HARD_NEGATIVES:
        res = resolver.resolve(query)
        if res is not None:
            offenders.append(f"{query!r} -> {res.symbol} (score {res.score:.1f})")
    assert not offenders, "confident-wrong on hard negatives:\n" + "\n".join(offenders)


def test_reliance_family_never_crosses(resolver: TickerResolver):
    assert resolver.resolve("Reliance Power").symbol == "RPOWER"
    assert resolver.resolve("Reliance Industries").symbol == "RELIANCE"
    assert resolver.resolve("RPOWER").symbol == "RPOWER"
    # bare 'Reliance' is ambiguous -> None, must not silently become RELIANCE or RPOWER
    assert resolver.resolve("Reliance") is None


def test_below_threshold_returns_none(resolver: TickerResolver):
    assert resolver.resolve("xyzzy not a company") is None
