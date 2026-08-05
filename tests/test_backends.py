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


@pytest.fixture()
def user_id(store):
    from core.repo import users as users_repo
    return users_repo.create(username="tester", password="testpass123")["id"]


def _proc(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=returncode,
                                       stdout=stdout, stderr=stderr)


# --------------------------------------------------------------------------- #
# claude_code
# --------------------------------------------------------------------------- #
def test_claude_code_missing_cli(store, user_id, monkeypatch):
    from core import backends

    monkeypatch.setattr(backends.shutil, "which", lambda _: None)
    info = backends.probe_claude_code(user_id)
    assert info.found is False
    assert info.ready is False
    assert "not found" in info.detail


def test_claude_code_probe_detects_a_deleted_install_dir(store, user_id, monkeypatch):
    """A service reinstalled/upgraded while still running ends up with its own cwd
    pointing at a directory that no longer exists — spawning `claude --version` into
    that then fails with a confusing, runtime-specific error (observed: Bun's own
    mangled ENOENT) instead of a clear one. Regression guard for that failure class."""
    from core import backends

    from pathlib import Path

    monkeypatch.setattr(backends.shutil, "which", lambda _: "/usr/bin/claude")
    monkeypatch.setattr(backends, "REPO_DIR", Path("/nonexistent/deleted/jobpilot-bundle"))
    info = backends.probe_claude_code(user_id)
    assert info.found is True
    assert "reinstalled/upgraded" in info.detail
    assert "jobpilot stop && jobpilot start" in info.detail


def test_claude_code_shallow_probe_does_not_verify_login(store, user_id, monkeypatch):
    from core import backends

    monkeypatch.setattr(backends.shutil, "which", lambda _: "/usr/bin/claude")
    monkeypatch.setattr(backends, "_run", lambda cmd, timeout=15, **kw: _proc(stdout="2.1.0"))
    info = backends.probe_claude_code(user_id, deep=False)
    assert info.found is True
    assert info.checked_deep is False
    assert "not verified" in info.detail


def test_claude_code_deep_probe_detects_logged_out(store, user_id, monkeypatch):
    from core import backends

    monkeypatch.setattr(backends.shutil, "which", lambda _: "/usr/bin/claude")

    def fake_run(cmd, timeout=15, **kw):
        if "--version" in cmd:
            return _proc(stdout="2.1.0")
        return _proc(returncode=1, stderr="Error: not logged in. Run `claude login`.")

    monkeypatch.setattr(backends, "_run", fake_run)
    info = backends.probe_claude_code(user_id, deep=True)
    # The v1 bug: `claude --version` exiting 0 was treated as "ready".
    assert info.found is True
    assert info.authenticated is False
    assert info.ready is False
    assert "claude login" in info.detail


def test_claude_code_deep_probe_success(store, user_id, monkeypatch):
    from core import backends

    monkeypatch.setattr(backends.shutil, "which", lambda _: "/usr/bin/claude")
    monkeypatch.setattr(
        backends, "_run",
        lambda cmd, timeout=15, **kw: _proc(stdout='{"result": "ok", "is_error": false}'
                                      if "-p" in cmd else "2.1.0"))
    info = backends.probe_claude_code(user_id, deep=True)
    assert info.ready is True


def test_claude_code_probe_handles_error_payload(store, user_id, monkeypatch):
    from core import backends

    monkeypatch.setattr(backends.shutil, "which", lambda _: "/usr/bin/claude")
    monkeypatch.setattr(
        backends, "_run",
        lambda cmd, timeout=15, **kw: _proc(stdout='{"is_error": true, "result": "quota"}'
                                      if "-p" in cmd else "2.1.0"))
    info = backends.probe_claude_code(user_id, deep=True)
    assert info.authenticated is False


# --------------------------------------------------------------------------- #
# claude_api
# --------------------------------------------------------------------------- #
def test_claude_api_needs_a_key(store, user_id, monkeypatch):
    from core import backends, secrets

    monkeypatch.setattr(secrets, "get", lambda uid, key: None)
    info = backends.probe_claude_api(user_id)
    assert info.ready is False
    assert "ANTHROPIC_API_KEY" in info.detail


def test_claude_api_deep_probe_rejects_bad_key(store, user_id, monkeypatch):
    from core import backends, secrets

    monkeypatch.setattr(secrets, "get", lambda uid, key: "sk-ant-bogus")
    monkeypatch.setattr(backends, "_anthropic_key_probe",
                        lambda key, timeout=20: (False, "key rejected"))
    info = backends.probe_claude_api(user_id, deep=True)
    assert info.authenticated is False
    assert info.detail == "key rejected"
    # The key is never echoed back in full.
    assert "sk-ant-bogus" not in str(info.as_dict())


# --------------------------------------------------------------------------- #
# generic_cli
# --------------------------------------------------------------------------- #
def test_generic_cli_requires_a_template(store, user_id):
    from core import backends

    info = backends.probe_generic_cli(user_id)
    assert info.found is False
    assert "template" in info.detail


def test_generic_cli_ready_when_binary_exists(store, user_id, monkeypatch):
    from core import backends

    # probe_generic_cli reads the instance-wide engine config (core/backends.py's own
    # cache_dir()/engine.json), not the per-user settings row — the agent backend is
    # shared across every account on this instance.
    monkeypatch.setattr(backends, "_load_engine_config",
                        lambda: {"provider": "generic_cli",
                                 "command_template": "mytool run --prompt {prompt}"})
    monkeypatch.setattr(backends.shutil, "which", lambda b: "/usr/bin/mytool")
    info = backends.probe_generic_cli(user_id)
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
def test_probe_all_covers_every_backend(store, user_id, monkeypatch):
    from core import backends

    monkeypatch.setattr(backends.shutil, "which", lambda _: None)
    monkeypatch.setattr(backends.secrets, "get", lambda uid, key: None)
    ids = [b["id"] for b in backends.probe_all(user_id)]
    assert ids == backends.PRIORITY
    assert backends.best_available(user_id) is None


def test_select_persists_engine_choice(store):
    """Backend selection is instance-wide (core/backends.py's own engine.json) — every
    account on the instance shares one agent backend, so this no longer touches the
    per-user settings row at all."""
    from core import backends

    backends.select("claude_api")
    assert backends._load_engine_config()["provider"] == "claude_api"
    assert backends.selected() == "claude_api"

    with pytest.raises(ValueError):
        backends.select("not_a_backend")


def test_default_permission_mode_bypasses_prompts(store, user_id):
    """Every phase runs headless with no one able to answer a permission prompt —
    the default must be one that never blocks on WebFetch/WebSearch/Bash, not just
    file edits. Regression guard for the discover-phase permission-prompt failure."""
    from core.repo import settings as settings_repo

    assert settings_repo.engine_config(user_id)["permission_mode"] == "bypassPermissions"


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
    usd = pricing.estimate(model="claude-opus-5", user_id=1, tokens_in=1_000_000, tokens_out=1_000_000)
    assert usd == pytest.approx(30.0)

    # Cache reads are a tenth of the input rate; writes 1.25×.
    cached = pricing.estimate(model="claude-opus-5", user_id=1, cache_read=1_000_000)
    assert cached == pytest.approx(0.5)
    written = pricing.estimate(model="claude-opus-5", user_id=1, cache_write=1_000_000)
    assert written == pytest.approx(6.25)


def test_pricing_unknown_claude_model_falls_back_not_free():
    from core import pricing

    usd = pricing.estimate(model="claude-something-new", user_id=1, tokens_in=1_000_000)
    assert usd > 0    # over-reporting beats silently reporting $0


def test_pricing_subscription_usage_costs_nothing_but_keeps_tokens():
    from core import pricing
    from engines.base import Usage

    usage = Usage(tokens_in=5000, tokens_out=2000, model="claude-opus-5",
                  source="subscription")
    usd, source = pricing.price_usage(usage, 1)
    assert usd == 0.0
    assert source == "subscription"


def test_pricing_prefers_provider_reported_cost():
    from core import pricing
    from engines.base import Usage

    usage = Usage(tokens_in=1000, tokens_out=1000, model="claude-opus-5",
                  source="metered", usd=0.4242)
    usd, source = pricing.price_usage(usage, 1)
    assert usd == pytest.approx(0.4242)
    assert source == "metered"


def test_pricing_overrides_from_settings(store, user_id):
    from core import pricing
    from core.repo import settings as settings_repo

    settings_repo.set(user_id, "pricing_overrides", {
        "claude-opus-5": {"input_per_mtok": 1.0, "output_per_mtok": 2.0}})
    assert pricing.estimate(model="claude-opus-5", user_id=user_id,
                            tokens_in=1_000_000) == pytest.approx(1.0)
    assert any(row["overridden"] for row in pricing.table(user_id))


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


# --------------------------------------------------------------------------- #
# tectonic — the optional PDF compiler
# --------------------------------------------------------------------------- #
def test_install_tectonic_is_a_no_op_when_already_present(monkeypatch):
    from core import backends

    monkeypatch.setattr(backends.shutil, "which", lambda name: "/usr/bin/tectonic")
    ok, message = backends.install_tectonic()
    assert ok and "already installed" in message


def test_install_tectonic_reports_a_download_failure_with_a_fallback(monkeypatch, tmp_path):
    """A dead network must produce a usable instruction, not a stack trace."""
    from core import backends

    monkeypatch.setattr(backends.shutil, "which", lambda name: None)
    monkeypatch.setattr(backends.platform, "system", lambda: "Linux")
    monkeypatch.setattr(backends, "_local_bin", lambda: str(tmp_path / "bin"))
    monkeypatch.setattr(backends, "tectonic_install_hints", lambda: ["sudo pacman -S tectonic"])

    import httpx
    monkeypatch.setattr(httpx, "get", lambda *a, **k: (_ for _ in ()).throw(
        httpx.ConnectError("no route to host")))

    ok, message = backends.install_tectonic()
    assert ok is False
    assert "sudo pacman -S tectonic" in message


def test_install_tectonic_flags_a_binary_that_is_not_on_path(monkeypatch, tmp_path):
    """Downloading into ~/.local/bin is useless if that isn't on PATH — say so."""
    from core import backends

    target = tmp_path / "bin"
    monkeypatch.setattr(backends.shutil, "which", lambda name: None)
    monkeypatch.setattr(backends.platform, "system", lambda: "Linux")
    monkeypatch.setattr(backends, "_local_bin", lambda: str(target))

    class FakeResponse:
        text = "#!/bin/sh\nexit 0\n"

        def raise_for_status(self):
            return self

    import httpx
    monkeypatch.setattr(httpx, "get", lambda *a, **k: FakeResponse())

    def fake_run(cmd, timeout=15, cwd=None):
        (target / "tectonic").write_text("binary")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(backends, "_run", fake_run)

    ok, message = backends.install_tectonic()
    assert ok is False                     # not usable yet, so don't claim success
    assert "not on your PATH" in message


def test_tectonic_hints_are_platform_specific(monkeypatch):
    from core import backends

    monkeypatch.setattr(backends.platform, "system", lambda: "Darwin")
    assert backends.tectonic_install_hints() == ["brew install tectonic"]

    monkeypatch.setattr(backends.platform, "system", lambda: "Linux")
    monkeypatch.setattr(backends.shutil, "which",
                        lambda name: "/usr/bin/pacman" if name == "pacman" else None)
    hints = backends.tectonic_install_hints()
    assert hints[0] == "sudo pacman -S tectonic"
    assert "cargo install tectonic" in hints        # always a last resort
