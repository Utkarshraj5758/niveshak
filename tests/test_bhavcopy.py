"""No-network tests for the bhavcopy downloader's correctness-critical helpers.

The single most dangerous bug in this layer is silently accepting a stale/echoed file for a
non-trading day (NSE's CDN returns HTTP 200 with the previous trading day's content for
weekend urls). These tests pin the two guards that prevent it: the expected-internal-date
formatter and the first-row date extractor used to validate every download.
"""

from datetime import date

from niveshak.market import bhavcopy


def test_expected_internal_date_matches_nse_format():
    assert bhavcopy._expected_internal_date(date(2026, 8, 14)) == "14-Aug-2026"
    assert bhavcopy._expected_internal_date(date(2024, 1, 3)) == "03-Jan-2024"


def test_first_data_date_reads_trimmed_date1():
    csv_text = (
        "SYMBOL, SERIES, DATE1, PREV_CLOSE\n"
        "RELIANCE, EQ, 14-Aug-2026, 100.0\n"
    )
    assert bhavcopy._first_data_date(csv_text) == "14-Aug-2026"


def test_first_data_date_none_when_header_only():
    assert bhavcopy._first_data_date("SYMBOL, SERIES, DATE1\n") is None


def test_validation_rejects_weekend_echo():
    # Sunday url would return Friday's file: internal date != requested date -> reject.
    requested = date(2026, 8, 16)  # Sunday
    echoed_friday = "SYMBOL, SERIES, DATE1\nX, EQ, 14-Aug-2026\n"
    assert bhavcopy._first_data_date(echoed_friday) != bhavcopy._expected_internal_date(requested)


def test_two_year_range_spans_two_years():
    start, end = bhavcopy.two_year_range(date(2026, 8, 19))
    assert (start, end) == (date(2024, 8, 19), date(2026, 8, 19))
