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
                     "logs", "db", "service", "migrate", "upgrade"}


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
    """Setup is now gated on account existence, not a settings flag: an instance with
    a reachable database but zero accounts still needs setup; creating the first
    account clears the gate. Per-account onboarding (resume, preferences, backend,
    delivery) happens in the browser from here on, not the CLI."""
    from core.repo import users as users_repo

    assert cli._needs_setup(store) is True
    users_repo.create(username="tester", password="testpass123")
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


# --------------------------------------------------------------------------- #
# upgrade
# --------------------------------------------------------------------------- #
def test_upgrade_check_on_a_checkout_never_touches_pypi(store, monkeypatch, capsys):
    """A source install must not have a published release pulled over the top of it."""
    monkeypatch.setattr(cli, "_install_source", lambda: ("local", "installed from /src"))
    monkeypatch.setattr(cli, "_latest_version",
                        lambda *a, **k: pytest.fail("PyPI must not be queried"))

    args = cli.build_parser().parse_args(["upgrade", "--check"])
    assert cli._upgrade(args) == 0

    out = capsys.readouterr().out
    assert "pipx install --force ." in out


def test_upgrade_check_reports_a_newer_release_without_installing(store, monkeypatch,
                                                                  capsys):
    monkeypatch.setattr(cli, "_install_source", lambda: ("pipx", "installed with pipx"))
    monkeypatch.setattr(cli, "_latest_version", lambda *a, **k: ("99.0.0", ""))
    monkeypatch.setattr(cli, "_post_upgrade",
                        lambda *a, **k: pytest.fail("--check must change nothing"))
    monkeypatch.setattr(cli.subprocess, "call",
                        lambda *a, **k: pytest.fail("--check must not install"))

    args = cli.build_parser().parse_args(["upgrade", "--check"])
    assert cli._upgrade(args) == 0
    assert "99.0.0" in capsys.readouterr().out


def test_upgrade_skips_the_installer_when_already_current(store, monkeypatch, capsys):
    from jobpilot import __version__

    monkeypatch.setattr(cli, "_install_source", lambda: ("pipx", "installed with pipx"))
    monkeypatch.setattr(cli, "_latest_version", lambda *a, **k: (__version__, ""))
    monkeypatch.setattr(cli.subprocess, "call",
                        lambda *a, **k: pytest.fail("nothing to install"))
    monkeypatch.setattr(cli, "_post_upgrade", lambda *a, **k: None)

    args = cli.build_parser().parse_args(["upgrade"])
    assert cli._upgrade(args) == 0
    assert "Already on the latest release" in capsys.readouterr().out


def test_upgrade_survives_an_unreachable_pypi(store, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_install_source", lambda: ("pipx", "installed with pipx"))
    monkeypatch.setattr(cli, "_latest_version", lambda *a, **k: (None, "no network"))
    monkeypatch.setattr(cli.subprocess, "call",
                        lambda *a, **k: pytest.fail("nothing to install"))
    monkeypatch.setattr(cli, "_post_upgrade", lambda *a, **k: None)

    # Offline is not a failure for a plain upgrade: the local fix-ups still run.
    args = cli.build_parser().parse_args(["upgrade"])
    assert cli._upgrade(args) == 0
    assert "no network" in capsys.readouterr().out


def test_upgrade_stops_when_the_installer_fails(store, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_install_source", lambda: ("pip", "installed with pip"))
    monkeypatch.setattr(cli, "_latest_version", lambda *a, **k: ("99.0.0", ""))
    monkeypatch.setattr(cli.subprocess, "call", lambda *a, **k: 1)
    monkeypatch.setattr(cli, "_post_upgrade",
                        lambda *a, **k: pytest.fail("must not run after a failed install"))

    args = cli.build_parser().parse_args(["upgrade"])
    assert cli._upgrade(args) == 1
    assert "upgrade failed" in capsys.readouterr().out


def test_post_upgrade_applies_migrations_and_exports(store, monkeypatch, capsys):
    from core.repo import users as users_repo

    monkeypatch.setattr("core.tailoring.has_tectonic", lambda: True)
    user_id = users_repo.create(username="tester", password="testpass123")["id"]

    cli._post_upgrade(interactive=False)

    out = capsys.readouterr().out
    assert "schema up to date" in out
    assert "preferences exported" in out
    assert "tectonic found" in out
    assert (store / "users" / str(user_id) / "options" / "preferences.json").exists()
