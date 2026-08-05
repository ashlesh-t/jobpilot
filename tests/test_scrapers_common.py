"""scripts/scrapers/_common.py — shared native-scraper helpers."""
from __future__ import annotations

import _common


def test_region_ok_passes_everything_for_global_and_both():
    assert _common.region_ok("Berlin, Germany", "global") is True
    assert _common.region_ok("Berlin, Germany", "both") is True
    assert _common.region_ok("", "global") is True


def test_region_ok_india_filters_non_india_locations():
    assert _common.region_ok("Bengaluru, India", "india") is True
    assert _common.region_ok("Remote", "india") is True
    assert _common.region_ok("", "india") is True  # unknown location — keep
    assert _common.region_ok("Berlin, Germany", "india") is False


def test_region_ok_us_filters_non_us_locations():
    assert _common.region_ok("Austin, TX", "us") is True
    assert _common.region_ok("Remote (USA)", "us") is True
    assert _common.region_ok("Remote", "us") is True
    assert _common.region_ok("", "us") is True  # unknown location — keep
    assert _common.region_ok("Berlin, Germany", "us") is False
    assert _common.region_ok("Bengaluru, India", "us") is False


def test_region_ok_us_does_not_false_match_bare_us_substring():
    """A bare 'us' token would false-match "Belarus"/"Mauritius"/"Austin" via naive
    substring search — regression guard for that class of bug."""
    assert _common.region_ok("Minsk, Belarus", "us") is False
    assert _common.region_ok("Port Louis, Mauritius", "us") is False
