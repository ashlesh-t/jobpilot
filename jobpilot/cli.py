"""`jobpilot` console entry point — cross-platform (Linux/macOS/Windows).

    jobpilot setup      guided setup: identity, database, AI backend, delivery
    jobpilot start      setup if needed → serve → open the web UI
    jobpilot serve      run the local service without opening a browser
    jobpilot stop       stop a running service
    jobpilot doctor     health table for backend, database, sources and delivery
    jobpilot view       inspect a single doctor row
    jobpilot logs       tail the service log
    jobpilot db         up | down | status | url
    jobpilot service    install | uninstall | status  (auto-start daemon)
    jobpilot migrate    import state from JobPilot v1
    jobpilot --version

Everything runs against the bundled runtime tree resolved by `jobpilot.paths`, so the
same commands work from a pipx install or a git checkout.

Job preferences, resume upload and the run schedule all live in the web UI — the CLI
only has to get the service running.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

from . import __version__
from .paths import bundle_root, inject_path, runtime_env


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _data_dir(override: str | None = None) -> Path:
    if override:
        return Path(os.path.expanduser(override))
    return Path(os.path.expanduser(os.environ.get("JOBPILOT_DIR", "~/.claude/job-hunt-ai")))


def _apply_data_dir(args: argparse.Namespace) -> None:
    """Make --data-dir visible to every child process and in-process import."""
    override = getattr(args, "data_dir", None)
    if override:
        os.environ["JOBPILOT_DIR"] = str(_data_dir(override))


def _runfile(args: argparse.Namespace | None = None) -> Path:
    return _data_dir(getattr(args, "data_dir", None) if args else None) / "cache" / "server.json"


def _read_runfile(args=None) -> dict | None:
    try:
        info = json.loads(_runfile(args).read_text())
    except Exception:
        return None
    return info if isinstance(info, dict) and info.get("pid") else None


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _resolve_port(host: str, port: int) -> int:
    inject_path()
    from common import find_available_port
    resolved = find_available_port(host, port)
    if resolved != port:
        print(f"==> Port {port} is already in use — using {resolved} instead.")
    return resolved


def _core():
    """Import the core package from the bundled tree."""
    inject_path()
    import core  # noqa: F401
    return core


# --------------------------------------------------------------------------- #
# setup / migrate
# --------------------------------------------------------------------------- #
def _setup(args: argparse.Namespace) -> int:
    _apply_data_dir(args)
    from .tui import run_setup
    return run_setup(non_interactive=getattr(args, "non_interactive", False))


def _migrate(args: argparse.Namespace) -> int:
    _apply_data_dir(args)
    _core()
    from core.db import init_db
    from core.migrate_v1 import migrate

    init_db()
    report = migrate(force=args.force)
    if not report["ran"]:
        print(f"skipped: {report['skipped_reason']}")
        return 0
    for key, value in report["counts"].items():
        print(f"  {key:16} {value}")
    for err in report["errors"]:
        print(f"  ! {err}")
    return 0


# --------------------------------------------------------------------------- #
# serve / start / stop
# --------------------------------------------------------------------------- #
def _serve(args: argparse.Namespace) -> int:
    _apply_data_dir(args)
    env = runtime_env()
    host = args.host or os.environ.get("JOBPILOT_HOST", "127.0.0.1")
    port = args.port or int(os.environ.get("JOBPILOT_PORT", "8787"))
    env["JOBPILOT_HOST"] = host
    env["JOBPILOT_PORT"] = str(_resolve_port(host, port))
    try:
        return subprocess.call([sys.executable, "-m", "server"],
                               cwd=str(bundle_root()), env=env)
    except KeyboardInterrupt:
        return 0


def _needs_setup(d: Path) -> bool:
    """True when setup has never completed on this data dir."""
    inject_path()
    try:
        from core.db import ping
        from core.repo import settings as settings_repo
        ok, _ = ping()
        return not (ok and settings_repo.is_setup_complete())
    except Exception:
        return True


def _start(args: argparse.Namespace) -> int:
    _apply_data_dir(args)
    d = _data_dir(args.data_dir)

    running = _read_runfile(args)
    if running and _pid_alive(running["pid"]):
        url = f"http://{running['host']}:{running['port']}"
        print(f"==> JobPilot is already running at {url} (pid {running['pid']}).")
        _open_browser(url)
        return 0

    if args.reconfigure or _needs_setup(d):
        code = _setup(args)
        if code != 0:
            return code
    else:
        print("==> Already configured — starting up (pass --reconfigure to redo setup).")

    _core()
    from core.db import init_db
    init_db()  # apply any migrations shipped since the last run

    host = args.host or os.environ.get("JOBPILOT_HOST", "127.0.0.1")
    port = _resolve_port(host, args.port or int(os.environ.get("JOBPILOT_PORT", "8787")))
    args.host, args.port = host, port
    url = f"http://{host}:{port}"

    if not args.no_browser:
        _open_browser(url, delay=1.5)
    print(f"==> Starting JobPilot → {url}")
    return _serve(args)


def _open_browser(url: str, delay: float = 0.0) -> None:
    def _open():
        if delay:
            time.sleep(delay)
        try:
            webbrowser.open(url)
        except Exception:
            pass
    if delay:
        import threading
        threading.Thread(target=_open, daemon=True).start()
    else:
        _open()


def _stop(args: argparse.Namespace) -> int:
    _apply_data_dir(args)
    info = _read_runfile(args)
    if not info:
        print("==> No running JobPilot service found.")
        return 0
    pid = int(info["pid"])
    if not _pid_alive(pid):
        print("==> Service already stopped (stale run file removed).")
        _runfile(args).unlink(missing_ok=True)
        return 0

    print(f"==> Stopping JobPilot (pid {pid})…")
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError as exc:
        print(f"==> Could not signal the process: {exc}")
        return 1

    for _ in range(20):  # up to 10s for a graceful shutdown
        if not _pid_alive(pid):
            print("==> Stopped.")
            _runfile(args).unlink(missing_ok=True)
            return 0
        time.sleep(0.5)

    print("==> Still running — sending SIGKILL.")
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass
    _runfile(args).unlink(missing_ok=True)
    return 0


# --------------------------------------------------------------------------- #
# doctor / view / logs
# --------------------------------------------------------------------------- #
def _doctor(args: argparse.Namespace) -> int:
    _apply_data_dir(args)
    inject_path()
    from core.db import init_db
    init_db()
    import doctor  # from server/, on sys.path via inject_path()

    report = doctor.run_doctor(bool(args.live))
    sym = {"ok": "  ok  ", " warn": "", "warn": " warn ", "fail": " FAIL "}
    width = max((len(r["name"]) for r in report["rows"]), default=10)
    for row in report["rows"]:
        print(f"[{sym.get(row['status'], '  ?   ')}] {row['name']:<{width}}  {row['detail']}")
    s = report["summary"]
    print(f"\n{s['ok']} ok · {s['warn']} warnings · {s['fail']} failures")
    return 1 if s["fail"] else 0


def _view(args: argparse.Namespace) -> int:
    _apply_data_dir(args)
    inject_path()
    from core.db import init_db
    init_db()
    import doctor

    report = doctor.run_doctor(bool(args.live))
    item = args.item.lower()
    exact = [r for r in report["rows"] if r["name"].lower() == item]
    matches = exact or [r for r in report["rows"] if item in r["name"].lower()]
    if not matches:
        print(f"No doctor item matches {args.item!r}. Valid items:")
        for r in report["rows"]:
            print(f"  - {r['name']}")
        return 1
    if len(matches) > 1:
        print(f"Ambiguous item {args.item!r}, matches:")
        for r in matches:
            print(f"  - {r['name']}")
        return 1
    row = matches[0]
    print(f"name:     {row['name']}")
    print(f"category: {row['category']}")
    print(f"status:   {row['status']}")
    print(f"detail:   {row['detail']}")
    return 0


def _logs(args: argparse.Namespace) -> int:
    _apply_data_dir(args)
    path = _data_dir(args.data_dir) / "logs" / "server.log"
    if not path.exists():
        print(f"==> No log file yet at {path}")
        print("    The service logs to the terminal when run in the foreground; the "
              "installed daemon writes here.")
        return 0
    if not args.follow:
        print(path.read_text()[-20000:])
        return 0
    print(f"==> Tailing {path} (Ctrl-C to stop)")
    try:
        with path.open() as fh:
            fh.seek(0, os.SEEK_END)
            while True:
                line = fh.readline()
                if line:
                    print(line, end="")
                else:
                    time.sleep(0.4)
    except KeyboardInterrupt:
        return 0


# --------------------------------------------------------------------------- #
# db
# --------------------------------------------------------------------------- #
def _db(args: argparse.Namespace) -> int:
    _apply_data_dir(args)
    _core()
    from core import db
    from core.infra import docker

    action = args.action
    if action == "up":
        result = docker.provision()
        print(f"==> {result['backend']}: {result['message']}")
        return 0
    if action == "down":
        if db.is_sqlite():
            print("==> Using SQLite — nothing to stop.")
            return 0
        ok, message = docker.stop()
        print(f"==> {message}")
        return 0 if ok else 1
    if action == "url":
        print(db.resolve_url())
        return 0

    ok, detail = db.ping()
    st = docker.status()
    print(f"backend:   {'sqlite' if db.is_sqlite() else 'postgresql'}")
    print(f"url:       {db.resolve_url()}")
    print(f"reachable: {'yes' if ok else 'no'} — {detail}")
    print(f"docker:    {st.detail}")
    return 0 if ok else 1


# --------------------------------------------------------------------------- #
# service (auto-start daemon)
# --------------------------------------------------------------------------- #
def _service(args: argparse.Namespace) -> int:
    _apply_data_dir(args)
    inject_path()
    import install_service  # from server/

    action = args.action
    if action == "install":
        return 0 if install_service.install() else 1
    if action == "uninstall":
        return 0 if install_service.uninstall() else 1
    for line in install_service.status():
        print(line)
    return 0


# --------------------------------------------------------------------------- #
# parser
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="jobpilot",
        description="JobPilot — your automated job hunt, running on your own machine.")
    p.add_argument("--version", action="version", version=f"jobpilot {__version__}")
    sub = p.add_subparsers(dest="cmd")

    def _common(sp):
        sp.add_argument("--data-dir", default=None,
                        help="override the data directory (default ~/.claude/job-hunt-ai)")
        return sp

    s = _common(sub.add_parser("setup", help="guided setup wizard"))
    s.add_argument("--non-interactive", action="store_true",
                   help="create the data dir and database without prompting")
    s.set_defaults(func=_setup)

    t = _common(sub.add_parser("start", help="setup if needed, then serve and open the UI"))
    t.add_argument("--reconfigure", action="store_true", help="re-run the setup wizard")
    t.add_argument("--no-browser", action="store_true", help="don't open a browser")
    t.add_argument("--non-interactive", action="store_true")
    t.add_argument("--host", default=None)
    t.add_argument("--port", type=int, default=None)
    t.set_defaults(func=_start)

    v = _common(sub.add_parser("serve", help="run the local service"))
    v.add_argument("--host", default=None)
    v.add_argument("--port", type=int, default=None)
    v.set_defaults(func=_serve)

    x = _common(sub.add_parser("stop", help="stop a running service"))
    x.set_defaults(func=_stop)

    d = _common(sub.add_parser("doctor", help="health check"))
    d.add_argument("--live", action="store_true",
                   help="also probe job sources and verify the backend login")
    d.set_defaults(func=_doctor)

    w = _common(sub.add_parser("view", help="inspect one doctor item by name"))
    w.add_argument("item", help="doctor row name or a unique substring, e.g. Apify")
    w.add_argument("--live", action="store_true")
    w.set_defaults(func=_view)

    lg = _common(sub.add_parser("logs", help="show the service log"))
    lg.add_argument("-f", "--follow", action="store_true", help="tail the log")
    lg.set_defaults(func=_logs)

    dbp = _common(sub.add_parser("db", help="database control"))
    dbp.add_argument("action", nargs="?", default="status",
                     choices=["up", "down", "status", "url"])
    dbp.set_defaults(func=_db)

    sv = _common(sub.add_parser("service", help="auto-start daemon control"))
    sv.add_argument("action", nargs="?", default="status",
                    choices=["install", "uninstall", "status"])
    sv.set_defaults(func=_service)

    mg = _common(sub.add_parser("migrate", help="import state from JobPilot v1"))
    mg.add_argument("--force", action="store_true", help="re-run even if already imported")
    mg.set_defaults(func=_migrate)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
