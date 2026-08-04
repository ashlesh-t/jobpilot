"""Unit tests for the Adzuna prompt added to `jobpilot setup` (step 4)."""
from __future__ import annotations

import pytest

from jobpilot.tui import prompts, steps


class FakeSecrets:
    def __init__(self, initial: dict | None = None):
        self._store = dict(initial or {})

    def has(self, key: str) -> bool:
        return bool(self._store.get(key))

    def get(self, key: str) -> str | None:
        return self._store.get(key)

    def mask(self, value: str | None) -> str:
        return "•masked•" if value else ""

    def set(self, key: str, value: str) -> None:
        self._store[key] = value


class Answers:
    """Feeds scripted answers to ask_confirm/ask_secret in call order."""

    def __init__(self, confirms: list[bool], secrets_: list[str]):
        self.confirms = list(confirms)
        self.secrets_ = list(secrets_)

    def confirm(self, *_a, **_k):
        return self.confirms.pop(0)

    def secret(self, *_a, **_k):
        return self.secrets_.pop(0)


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    # Silence all output so tests only assert on side effects.
    for name in ("out", "info", "success", "warn", "error", "panel", "qr", "step_header"):
        monkeypatch.setattr(steps.theme, name, lambda *a, **k: None)


def test_verify_adzuna_success(monkeypatch):
    class Resp:
        status_code = 200

    monkeypatch.setattr("requests.get", lambda *a, **k: Resp())
    ok, detail = steps._verify_adzuna("id123", "key456")
    assert ok is True
    assert detail == "credentials valid"


def test_verify_adzuna_rejected(monkeypatch):
    class Resp:
        status_code = 401

    monkeypatch.setattr("requests.get", lambda *a, **k: Resp())
    ok, detail = steps._verify_adzuna("bad", "bad")
    assert ok is False
    assert "rejected" in detail


def test_verify_adzuna_network_error(monkeypatch):
    def boom(*a, **k):
        raise OSError("no route to host")

    monkeypatch.setattr("requests.get", boom)
    ok, detail = steps._verify_adzuna("id", "key")
    assert ok is False
    assert "Could not reach Adzuna" in detail


def test_setup_adzuna_user_declines(monkeypatch):
    secrets = FakeSecrets()
    answers = Answers(confirms=[False], secrets_=[])
    monkeypatch.setattr(prompts, "ask_confirm", answers.confirm)
    monkeypatch.setattr(prompts, "ask_secret", answers.secret)

    steps._setup_adzuna(secrets)

    assert not secrets.has("ADZUNA_APP_ID")
    assert not secrets.has("ADZUNA_APP_KEY")


def test_setup_adzuna_already_configured_keeps_existing(monkeypatch):
    secrets = FakeSecrets({"ADZUNA_APP_ID": "old-id", "ADZUNA_APP_KEY": "old-key"})
    # First confirm: "Replace it?" -> False, so we stop right there.
    answers = Answers(confirms=[False], secrets_=[])
    monkeypatch.setattr(prompts, "ask_confirm", answers.confirm)
    monkeypatch.setattr(prompts, "ask_secret", answers.secret)

    steps._setup_adzuna(secrets)

    assert secrets.get("ADZUNA_APP_ID") == "old-id"
    assert secrets.get("ADZUNA_APP_KEY") == "old-key"


def test_setup_adzuna_valid_credentials_are_stored(monkeypatch):
    secrets = FakeSecrets()
    answers = Answers(confirms=[True], secrets_=["new-id", "new-key"])
    monkeypatch.setattr(prompts, "ask_confirm", answers.confirm)
    monkeypatch.setattr(prompts, "ask_secret", answers.secret)
    monkeypatch.setattr(steps, "_verify_adzuna", lambda *_a: (True, "credentials valid"))

    steps._setup_adzuna(secrets)

    assert secrets.get("ADZUNA_APP_ID") == "new-id"
    assert secrets.get("ADZUNA_APP_KEY") == "new-key"


def test_setup_adzuna_invalid_credentials_declined_save(monkeypatch):
    secrets = FakeSecrets()
    # confirm order: "Add Adzuna now?" -> True, "Save it anyway?" -> False
    answers = Answers(confirms=[True, False], secrets_=["bad-id", "bad-key"])
    monkeypatch.setattr(prompts, "ask_confirm", answers.confirm)
    monkeypatch.setattr(prompts, "ask_secret", answers.secret)
    monkeypatch.setattr(steps, "_verify_adzuna", lambda *_a: (False, "Adzuna rejected that pair"))

    steps._setup_adzuna(secrets)

    assert not secrets.has("ADZUNA_APP_ID")
    assert not secrets.has("ADZUNA_APP_KEY")


def test_setup_adzuna_invalid_credentials_save_anyway(monkeypatch):
    secrets = FakeSecrets()
    answers = Answers(confirms=[True, True], secrets_=["bad-id", "bad-key"])
    monkeypatch.setattr(prompts, "ask_confirm", answers.confirm)
    monkeypatch.setattr(prompts, "ask_secret", answers.secret)
    monkeypatch.setattr(steps, "_verify_adzuna", lambda *_a: (False, "Adzuna rejected that pair"))

    steps._setup_adzuna(secrets)

    assert secrets.get("ADZUNA_APP_ID") == "bad-id"
    assert secrets.get("ADZUNA_APP_KEY") == "bad-key"


def test_setup_adzuna_empty_app_id_skips(monkeypatch):
    secrets = FakeSecrets()
    answers = Answers(confirms=[True], secrets_=[""])
    monkeypatch.setattr(prompts, "ask_confirm", answers.confirm)
    monkeypatch.setattr(prompts, "ask_secret", answers.secret)

    steps._setup_adzuna(secrets)

    assert not secrets.has("ADZUNA_APP_ID")
