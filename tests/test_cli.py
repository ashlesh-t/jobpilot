"""Unit tests for jobpilot/cli.py — argument parsing and process helpers, no server.

Schedule configuration moved out of the CLI into the web UI in v2; the slot naming and
validation rules it used to own now live in core.repo.schedule (see test_core_repo.py).
"""
from __future__ import annotations

import json
import os

import pytest

from jobpilot import cli


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBPILOT_DIR", str(tmp_path))
    monkeypatch.delenv("JOBPILOT_DATABASE_URL", raising=False)
    from core import db

    db.dispose()
    db.init_db()
    yield tmp_path
    db.dispose()


# --------------------------------------------------------------------------- #
# parser
# --------------------------------------------------------------------------- #
def test_parser_exposes_every_subcommand():
    parser = cli.build_parser()
    actions = [a for a in parser._actions if a.dest == "cmd"]
    assert actions, "expected a subparser group"
    names = set(actions[0].choices)
    assert names == {"setup", "start", "serve", "stop", "doctor", "view",
                     "logs", "db", "service", "migrate"}


def test_parser_defaults():
    parser = cli.build_parser()
    args = parser.parse_args(["db"])
    assert args.action == "status"
    args = parser.parse_args(["service"])
    assert args.action == "status"
    args = parser.parse_args(["doctor", "--live"])
    assert args.live is True


def test_no_subcommand_prints_help(capsys):
    assert cli.main([]) == 0
    assert "jobpilot" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# data dir resolution
# --------------------------------------------------------------------------- #
def test_data_dir_precedence(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBPILOT_DIR", str(tmp_path / "from-env"))
    assert cli._data_dir() == tmp_path / "from-env"
    assert cli._data_dir(str(tmp_path / "explicit")) == tmp_path / "explicit"


def test_apply_data_dir_exports_to_environment(tmp_path, monkeypatch):
    monkeypatch.delenv("JOBPILOT_DIR", raising=False)
    args = cli.build_parser().parse_args(["serve", "--data-dir", str(tmp_path)])
    cli._apply_data_dir(args)
    assert os.environ["JOBPILOT_DIR"] == str(tmp_path)


# --------------------------------------------------------------------------- #
# run file / stop
# --------------------------------------------------------------------------- #
def test_read_runfile_ignores_garbage(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBPILOT_DIR", str(tmp_path))
    (tmp_path / "cache").mkdir(parents=True)
    assert cli._read_runfile() is None

    cli._runfile().write_text("not json")
    assert cli._read_runfile() is None

    cli._runfile().write_text(json.dumps({"host": "127.0.0.1"}))  # no pid
    assert cli._read_runfile() is None

    cli._runfile().write_text(json.dumps({"pid": 123, "host": "127.0.0.1", "port": 8787}))
    assert cli._read_runfile()["pid"] == 123


def test_stop_with_no_service(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("JOBPILOT_DIR", str(tmp_path))
    args = cli.build_parser().parse_args(["stop"])
    assert cli._stop(args) == 0
    assert "No running JobPilot service" in capsys.readouterr().out


def test_stop_clears_a_stale_runfile(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("JOBPILOT_DIR", str(tmp_path))
    (tmp_path / "cache").mkdir(parents=True)
    cli._runfile().write_text(json.dumps({"pid": 999999, "host": "127.0.0.1", "port": 8787}))
    monkeypatch.setattr(cli, "_pid_alive", lambda pid: False)

    args = cli.build_parser().parse_args(["stop"])
    assert cli._stop(args) == 0
    assert not cli._runfile().exists()
    assert "already stopped" in capsys.readouterr().out


def test_stop_signals_then_confirms(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("JOBPILOT_DIR", str(tmp_path))
    (tmp_path / "cache").mkdir(parents=True)
    cli._runfile().write_text(json.dumps({"pid": 4242, "host": "127.0.0.1", "port": 8787}))

    signalled = []
    alive = iter([True, False, False])
    monkeypatch.setattr(cli, "_pid_alive", lambda pid: next(alive, False))
    monkeypatch.setattr(cli.os, "kill", lambda pid, sig: signalled.append((pid, sig)))

    args = cli.build_parser().parse_args(["stop"])
    assert cli._stop(args) == 0
    assert signalled and signalled[0][0] == 4242
    assert not cli._runfile().exists()
    assert "Stopped." in capsys.readouterr().out


def test_pid_alive_for_this_process():
    assert cli._pid_alive(os.getpid()) is True
    assert cli._pid_alive(999999) is False


# --------------------------------------------------------------------------- #
# setup gate
# --------------------------------------------------------------------------- #
def test_needs_setup_until_marked_complete(store):
    from core.repo import settings as settings_repo

    assert cli._needs_setup(store) is True
    settings_repo.mark_setup_complete(True)
    assert cli._needs_setup(store) is False


def test_start_short_circuits_when_already_running(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("JOBPILOT_DIR", str(tmp_path))
    (tmp_path / "cache").mkdir(parents=True)
    cli._runfile().write_text(json.dumps({"pid": 4242, "host": "127.0.0.1", "port": 8787}))
    monkeypatch.setattr(cli, "_pid_alive", lambda pid: True)
    opened = []
    monkeypatch.setattr(cli, "_open_browser", lambda url, delay=0: opened.append(url))

    args = cli.build_parser().parse_args(["start"])
    assert cli._start(args) == 0
    assert opened == ["http://127.0.0.1:8787"]
    assert "already running" in capsys.readouterr().out


def test_setup_non_interactive_provisions_a_database(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("JOBPILOT_DIR", str(tmp_path))
    monkeypatch.delenv("JOBPILOT_DATABASE_URL", raising=False)

    from core import db
    from core.infra import docker

    # Pretend Docker is unavailable so the test exercises the SQLite fallback path
    # rather than touching a real container.
    monkeypatch.setattr(docker, "ensure_postgres",
                        lambda **kw: (None, "docker CLI not found on PATH"))
    db.dispose()

    args = cli.build_parser().parse_args(["setup", "--non-interactive"])
    assert cli._setup(args) == 0
    out = capsys.readouterr().out
    assert "sqlite" in out
    assert (tmp_path / "cache" / "jobpilot.db").exists()
    db.dispose()
