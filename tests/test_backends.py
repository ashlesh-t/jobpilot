"""Backend detection, pricing, and engine-adapter tests.

These never call a real provider — every probe is monkeypatched — so the suite stays
fast and works offline.
"""
from __future__ import annotations

import subprocess

import pytest


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBPILOT_DIR", str(tmp_path))
    monkeypatch.delenv("JOBPILOT_DATABASE_URL", raising=False)
    from core import db

    db.dispose()
    db.init_db()
    yield tmp_path
    db.dispose()


def _proc(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=returncode,
                                       stdout=stdout, stderr=stderr)


# --------------------------------------------------------------------------- #
# claude_code
# --------------------------------------------------------------------------- #
def test_claude_code_missing_cli(store, monkeypatch):
    from core import backends

    monkeypatch.setattr(backends.shutil, "which", lambda _: None)
    info = backends.probe_claude_code()
    assert info.found is False
    assert info.ready is False
    assert "not found" in info.detail


def test_claude_code_shallow_probe_does_not_verify_login(store, monkeypatch):
    from core import backends

    monkeypatch.setattr(backends.shutil, "which", lambda _: "/usr/bin/claude")
    monkeypatch.setattr(backends, "_run", lambda cmd, timeout=15: _proc(stdout="2.1.0"))
    info = backends.probe_claude_code(deep=False)
    assert info.found is True
    assert info.checked_deep is False
    assert "not verified" in info.detail


def test_claude_code_deep_probe_detects_logged_out(store, monkeypatch):
    from core import backends

    monkeypatch.setattr(backends.shutil, "which", lambda _: "/usr/bin/claude")

    def fake_run(cmd, timeout=15):
        if "--version" in cmd:
            return _proc(stdout="2.1.0")
        return _proc(returncode=1, stderr="Error: not logged in. Run `claude login`.")

    monkeypatch.setattr(backends, "_run", fake_run)
    info = backends.probe_claude_code(deep=True)
    # The v1 bug: `claude --version` exiting 0 was treated as "ready".
    assert info.found is True
    assert info.authenticated is False
    assert info.ready is False
    assert "claude login" in info.detail


def test_claude_code_deep_probe_success(store, monkeypatch):
    from core import backends

    monkeypatch.setattr(backends.shutil, "which", lambda _: "/usr/bin/claude")
    monkeypatch.setattr(
        backends, "_run",
        lambda cmd, timeout=15: _proc(stdout='{"result": "ok", "is_error": false}'
                                      if "-p" in cmd else "2.1.0"))
    info = backends.probe_claude_code(deep=True)
    assert info.ready is True


def test_claude_code_probe_handles_error_payload(store, monkeypatch):
    from core import backends

    monkeypatch.setattr(backends.shutil, "which", lambda _: "/usr/bin/claude")
    monkeypatch.setattr(
        backends, "_run",
        lambda cmd, timeout=15: _proc(stdout='{"is_error": true, "result": "quota"}'
                                      if "-p" in cmd else "2.1.0"))
    info = backends.probe_claude_code(deep=True)
    assert info.authenticated is False


# --------------------------------------------------------------------------- #
# claude_api
# --------------------------------------------------------------------------- #
def test_claude_api_needs_a_key(store, monkeypatch):
    from core import backends, secrets

    monkeypatch.setattr(secrets, "get", lambda key: None)
    info = backends.probe_claude_api()
    assert info.ready is False
    assert "ANTHROPIC_API_KEY" in info.detail


def test_claude_api_deep_probe_rejects_bad_key(store, monkeypatch):
    from core import backends, secrets

    monkeypatch.setattr(secrets, "get", lambda key: "sk-ant-bogus")
    monkeypatch.setattr(backends, "_anthropic_key_probe",
                        lambda key, timeout=20: (False, "key rejected"))
    info = backends.probe_claude_api(deep=True)
    assert info.authenticated is False
    assert info.detail == "key rejected"
    # The key is never echoed back in full.
    assert "sk-ant-bogus" not in str(info.as_dict())


# --------------------------------------------------------------------------- #
# generic_cli
# --------------------------------------------------------------------------- #
def test_generic_cli_requires_a_template(store):
    from core import backends

    info = backends.probe_generic_cli()
    assert info.found is False
    assert "template" in info.detail


def test_generic_cli_ready_when_binary_exists(store, monkeypatch):
    from core import backends
    from core.repo import settings as settings_repo

    settings_repo.set("engine", {"provider": "generic_cli",
                                 "command_template": "mytool run --prompt {prompt}"})
    monkeypatch.setattr(backends.shutil, "which", lambda b: "/usr/bin/mytool")
    info = backends.probe_generic_cli()
    assert info.ready is True


def test_generic_cli_builds_command_without_shell_injection(store):
    from engines.generic_cli import GenericCliEngine

    eng = GenericCliEngine(command_template="mytool run --yes --prompt {prompt}")
    cmd = eng.build_command("/job-search", "run1")
    assert cmd[:4] == ["mytool", "run", "--yes", "--prompt"]
    # The whole program text is one argv entry — quotes or spaces inside it can
    # never become extra shell words.
    assert len(cmd) == 5
    assert "/job-search" in cmd[4]


def test_generic_cli_rejects_template_without_prompt(store):
    from engines.generic_cli import GenericCliEngine

    ok, reason = GenericCliEngine(command_template="mytool run").available()
    assert ok is False
    assert "{prompt}" in reason


# --------------------------------------------------------------------------- #
# registry + selection
# --------------------------------------------------------------------------- #
def test_probe_all_covers_every_backend(store, monkeypatch):
    from core import backends

    monkeypatch.setattr(backends.shutil, "which", lambda _: None)
    monkeypatch.setattr(backends.secrets, "get", lambda key: None)
    ids = [b["id"] for b in backends.probe_all()]
    assert ids == backends.PRIORITY
    assert backends.best_available() is None


def test_select_persists_engine_choice(store):
    from core import backends
    from core.repo import settings as settings_repo

    backends.select("claude_api")
    assert settings_repo.engine_config()["provider"] == "claude_api"
    assert backends.selected() == "claude_api"

    with pytest.raises(ValueError):
        backends.select("not_a_backend")


def test_engine_registry_lists_all_four(store):
    import engines

    names = {e["name"] for e in engines.list_engines()}
    assert names == {"claude_code", "claude_api", "gemini", "generic_cli"}


# --------------------------------------------------------------------------- #
# pricing
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("model,expected", [
    ("claude-opus-5", "claude-opus-5"),
    ("claude-opus-5-20260101", "claude-opus-5"),
    ("anthropic.claude-sonnet-5", "claude-sonnet-5"),
    ("gpt-nonsense", "gpt-nonsense"),
])
def test_pricing_normalizes_model_ids(model, expected):
    from core import pricing

    assert pricing.normalize(model) == expected


def test_pricing_estimate_matches_published_rates():
    from core import pricing

    # Opus 5: $5 / MTok in, $25 / MTok out.
    usd = pricing.estimate(model="claude-opus-5", tokens_in=1_000_000, tokens_out=1_000_000)
    assert usd == pytest.approx(30.0)

    # Cache reads are a tenth of the input rate; writes 1.25×.
    cached = pricing.estimate(model="claude-opus-5", cache_read=1_000_000)
    assert cached == pytest.approx(0.5)
    written = pricing.estimate(model="claude-opus-5", cache_write=1_000_000)
    assert written == pytest.approx(6.25)


def test_pricing_unknown_claude_model_falls_back_not_free():
    from core import pricing

    usd = pricing.estimate(model="claude-something-new", tokens_in=1_000_000)
    assert usd > 0    # over-reporting beats silently reporting $0


def test_pricing_subscription_usage_costs_nothing_but_keeps_tokens():
    from core import pricing
    from engines.base import Usage

    usage = Usage(tokens_in=5000, tokens_out=2000, model="claude-opus-5",
                  source="subscription")
    usd, source = pricing.price_usage(usage)
    assert usd == 0.0
    assert source == "subscription"


def test_pricing_prefers_provider_reported_cost():
    from core import pricing
    from engines.base import Usage

    usage = Usage(tokens_in=1000, tokens_out=1000, model="claude-opus-5",
                  source="metered", usd=0.4242)
    usd, source = pricing.price_usage(usage)
    assert usd == pytest.approx(0.4242)
    assert source == "metered"


def test_pricing_overrides_from_settings(store):
    from core import pricing
    from core.repo import settings as settings_repo

    settings_repo.set("pricing_overrides", {
        "claude-opus-5": {"input_per_mtok": 1.0, "output_per_mtok": 2.0}})
    assert pricing.estimate(model="claude-opus-5", tokens_in=1_000_000) == pytest.approx(1.0)
    assert any(row["overridden"] for row in pricing.table())


# --------------------------------------------------------------------------- #
# usage accumulation on the engines
# --------------------------------------------------------------------------- #
def test_claude_code_absorbs_usage_from_stream():
    from engines.claude_code import ClaudeCodeEngine

    eng = ClaudeCodeEngine()
    events = []
    eng._handle_line(
        '{"type":"assistant","message":{"model":"claude-opus-5",'
        '"usage":{"input_tokens":100,"output_tokens":40,'
        '"cache_read_input_tokens":900},"content":[]}}',
        events.append)
    final = eng._handle_line(
        '{"type":"result","result":"done","total_cost_usd":0.05,'
        '"usage":{"input_tokens":10,"output_tokens":5}}',
        events.append)

    assert final == "done"
    assert eng._usage.tokens_in == 110
    assert eng._usage.tokens_out == 45
    assert eng._usage.cache_read == 900
    assert eng._usage.model == "claude-opus-5"
    assert eng._usage.source == "subscription"


def test_usage_merge_accumulates():
    from engines.base import Usage

    a = Usage(tokens_in=10, tokens_out=5, source="estimated")
    b = Usage(tokens_in=3, tokens_out=2, model="claude-opus-5", source="metered")
    merged = a.merge(b)
    assert (merged.tokens_in, merged.tokens_out) == (13, 7)
    assert merged.model == "claude-opus-5"
    assert merged.source == "metered"


def test_secrets_masking_never_leaks_the_middle():
    from core import secrets

    masked = secrets.mask("sk-ant-api03-abcdefghijklmnop9f2a")
    assert masked.startswith("sk-ant")
    assert masked.endswith("9f2a")
    assert "abcdefghijklmnop" not in masked
    assert secrets.mask("") == ""
    assert secrets.mask("short") == "•••••"
