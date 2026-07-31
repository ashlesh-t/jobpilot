"""Unit tests for jobpilot/cli.py's `start`/`view` helpers (no server/network involved)."""
import json
from pathlib import Path

from jobpilot import cli


def test_configured_requires_prefs_and_db(tmp_path):
    assert cli._configured(tmp_path) is False
    (tmp_path / "options").mkdir()
    (tmp_path / "options" / "preferences.json").write_text("{}")
    assert cli._configured(tmp_path) is False
    (tmp_path / "cache").mkdir()
    (tmp_path / "cache" / "jobs.sqlite").write_text("")
    assert cli._configured(tmp_path) is True


def test_prompt_schedule_slots_disambiguates_duplicates(monkeypatch):
    answers = iter(["09:30", "morning", "18:00", "evening", "18:00", "evening", ""])
    monkeypatch.setattr("builtins.input", lambda *_: next(answers))
    slots = cli._prompt_schedule_slots()
    assert slots == [
        {"name": "morning", "time": "09:30"},
        {"name": "evening-1", "time": "18:00"},
        {"name": "evening-2", "time": "18:00"},
    ]


def test_prompt_schedule_slots_rejects_bad_time(monkeypatch, capsys):
    answers = iter(["25:99", "9:30", "09:30", "x", ""])
    monkeypatch.setattr("builtins.input", lambda *_: next(answers))
    slots = cli._prompt_schedule_slots()
    assert slots == [{"name": "x", "time": "09:30"}]
    assert "invalid time" in capsys.readouterr().out


def test_configure_schedule_appends_to_existing(tmp_path, monkeypatch):
    (tmp_path / "options").mkdir()
    prefs_path = tmp_path / "options" / "preferences.json"
    prefs_path.write_text(json.dumps({"schedule_slots_ist": ["07:00"], "other": "keep-me"}))

    answers = iter(["09:30", "morning", ""])
    monkeypatch.setattr("builtins.input", lambda *_: next(answers))
    cli._configure_schedule(tmp_path)

    saved = json.loads(prefs_path.read_text())
    assert saved["other"] == "keep-me"
    assert saved["schedule_slots_ist"] == ["07:00", {"name": "morning", "time": "09:30"}]


def test_configure_schedule_noop_when_nothing_entered(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda *_: "")
    cli._configure_schedule(tmp_path)
    assert not (tmp_path / "options" / "preferences.json").exists()
    assert "leaving the existing schedule as-is" in capsys.readouterr().out
