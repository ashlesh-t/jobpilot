"""scripts/scrapers/ats_boards.py — company-focus filtering, no network."""
from __future__ import annotations

import ats_boards


def test_slug_strips_non_alnum():
    assert ats_boards._slug("Infra.Market") == "inframarket"
    assert ats_boards._slug("CRED") == "cred"


def test_load_companies_only_returns_entries_with_ats_and_token(tmp_path, monkeypatch):
    cfg = tmp_path / "target_companies.json"
    cfg.write_text('''{
      "enabled": true,
      "companies": [
        {"name": "Stripe", "focus": "global", "ats": "greenhouse", "token": "stripe"},
        {"name": "Google", "focus": "global", "ats": null},
        {"name": "NoToken", "focus": "global", "ats": "lever"}
      ]
    }''')
    monkeypatch.setattr(ats_boards, "TARGET_COMPANIES_PATH", cfg)
    companies = ats_boards._load_companies()
    assert [c["name"] for c in companies] == ["Stripe"]


def test_load_companies_respects_enabled_flag(tmp_path, monkeypatch):
    cfg = tmp_path / "target_companies.json"
    cfg.write_text('{"enabled": false, "companies": [{"name": "Stripe", "ats": "greenhouse", "token": "stripe"}]}')
    monkeypatch.setattr(ats_boards, "TARGET_COMPANIES_PATH", cfg)
    assert ats_boards._load_companies() == []


def test_fetch_returns_empty_with_no_companies_configured(tmp_path, monkeypatch):
    cfg = tmp_path / "target_companies.json"
    cfg.write_text('{"enabled": true, "companies": []}')
    monkeypatch.setattr(ats_boards, "TARGET_COMPANIES_PATH", cfg)
    assert ats_boards.fetch(focus="both") == []


def test_fetch_skips_companies_outside_the_run_focus(tmp_path, monkeypatch):
    """An india-tagged company must not be probed on a global-focus run and vice versa —
    regression guard so we never burn a request on an irrelevant company."""
    cfg = tmp_path / "target_companies.json"
    cfg.write_text('''{
      "enabled": true,
      "companies": [
        {"name": "Stripe", "focus": "global", "ats": "greenhouse", "token": "stripe"},
        {"name": "CRED", "focus": "india", "ats": "lever", "token": "cred"}
      ]
    }''')
    monkeypatch.setattr(ats_boards, "TARGET_COMPANIES_PATH", cfg)

    called = []
    monkeypatch.setitem(ats_boards._FETCHERS, "greenhouse",
                        lambda token, company, focus, cap: called.append(company) or [])
    monkeypatch.setitem(ats_boards._FETCHERS, "lever",
                        lambda token, company, focus, cap: called.append(company) or [])

    ats_boards.fetch(focus="india")
    assert called == ["CRED"]

    called.clear()
    ats_boards.fetch(focus="global")
    assert called == ["Stripe"]

    called.clear()
    ats_boards.fetch(focus="both")
    assert set(called) == {"Stripe", "CRED"}
