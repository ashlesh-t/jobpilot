"""`jobpilot` console entry point — cross-platform (Linux/macOS/Windows).

Subcommands:
  jobpilot setup     configure the data dir, DB, config, slash commands (stdlib only)
  jobpilot serve     launch the local control service + web UI
  jobpilot doctor    print an engines/notifiers/sources health table
  jobpilot view      inspect a single doctor row by name
  jobpilot start     one-shot bootstrap: setup (if needed) -> schedule slots -> serve
  jobpilot --version

Each subcommand runs against the bundled runtime tree resolved by jobpilot.paths, so the
same command works from a pipx install or a git checkout.

Note: `jobpilot start` cannot install the Claude Code plugin that registers the `/job-*`
skills — that step (`/plugin install jobpilot@jobpilot`) runs inside Claude Code, not the
shell, and stays a separate one-time step. See README "Install".
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import webbrowser
from pathlib import Path

from . import __version__
from .paths import bundle_root, runtime_env, inject_path


def _resolve_port(host: str, port: int) -> int:
    inject_path()
    from common import find_available_port
    resolved = find_available_port(host, port)
    if resolved != port:
        print(f"==> Port {port} is already in use — using {resolved} instead.")
    return resolved


def _setup(args: argparse.Namespace) -> int:
    root = bundle_root()
    script = root / "scripts" / "jobpilot_setup.py"
    # Installed via pipx → deps already present in the isolated venv, so --no-deps.
    passthrough = ["--no-deps"]
    if args.no_wizard:
        passthrough.append("--no-wizard")
    if args.data_dir:
        passthrough += ["--data-dir", args.data_dir]
    return subprocess.call([sys.executable, str(script), *passthrough],
                           cwd=str(root), env=runtime_env())


def _serve(args: argparse.Namespace) -> int:
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


def _doctor(args: argparse.Namespace) -> int:
    root = bundle_root()
    live = "True" if args.live else "False"
    code = (
        "import doctor\n"
        f"r = doctor.run_doctor({live})\n"
        "sym = {'ok': 'OK ', 'warn': '!! ', 'fail': 'XX '}\n"
        "for x in r['rows']:\n"
        "    print(sym.get(x['status'], '?  ') + x['name'] + '  [' + x['category'] + ']  ' + x['detail'])\n"
        "print('summary:', r['summary'])\n"
    )
    return subprocess.call([sys.executable, "-c", code],
                           cwd=str(root / "server"), env=runtime_env())


def _data_dir(override: str | None) -> Path:
    if override:
        return Path(os.path.expanduser(override))
    raw = os.environ.get("JOBPILOT_DIR", "~/.claude/job-hunt-ai")
    return Path(os.path.expanduser(raw))


def _view(args) -> int:
    root = bundle_root()
    code = (
        "import doctor, sys\n"
        f"r = doctor.run_doctor({'True' if args.live else 'False'})\n"
        f"item = {args.item!r}\n"
        "exact = [x for x in r['rows'] if x['name'].lower() == item.lower()]\n"
        "matches = exact or [x for x in r['rows'] if item.lower() in x['name'].lower()]\n"
        "if not matches:\n"
        "    print(f'No doctor item matches {item!r}.')\n"
        "    print('Valid items:')\n"
        "    for x in r['rows']:\n"
        "        print('  - ' + x['name'])\n"
        "    sys.exit(1)\n"
        "if len(matches) > 1:\n"
        "    print(f'Ambiguous item {item!r}, matches:')\n"
        "    for x in matches:\n"
        "        print('  - ' + x['name'])\n"
        "    sys.exit(1)\n"
        "x = matches[0]\n"
        "sym = {'ok': 'OK ', 'warn': '!! ', 'fail': 'XX '}\n"
        "print('name:    ', x['name'])\n"
        "print('category:', x['category'])\n"
        "print('status:  ', sym.get(x['status'], '?  ') + x['status'])\n"
        "print('detail:  ', x['detail'])\n"
    )
    return subprocess.call([sys.executable, "-c", code],
                           cwd=str(root / "server"), env=runtime_env())


_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def _configured(d: Path) -> bool:
    return (d / "options" / "preferences.json").exists() and (d / "cache" / "jobs.sqlite").exists()


def _prompt_schedule_slots() -> list[dict]:
    """Interactively collect (name, HH:MM) pairs; disambiguate repeated names with -1/-2/…"""
    print("\n==> Schedule automatic runs (24-hour HH:MM, Asia/Kolkata). Leave time blank to stop.")
    raw: list[tuple[str, str]] = []
    while True:
        n = len(raw) + 1
        t = input(f"  Slot {n} time (blank to finish): ").strip()
        if not t:
            break
        if not _TIME_RE.match(t):
            print("    invalid time — expected 24h HH:MM, e.g. 09:30 or 18:00")
            continue
        name = input(f"  Slot {n} name [default: slot]: ").strip() or "slot"
        raw.append((name, t))

    counts: dict[str, int] = {}
    for name, _ in raw:
        counts[name] = counts.get(name, 0) + 1
    seen: dict[str, int] = {}
    slots = []
    for name, t in raw:
        if counts[name] > 1:
            seen[name] = seen.get(name, 0) + 1
            final_name = f"{name}-{seen[name]}"
        else:
            final_name = name
        slots.append({"name": final_name, "time": t})
    return slots


def _configure_schedule(d: Path) -> None:
    new_slots = _prompt_schedule_slots()
    if not new_slots:
        print("==> No schedule slots entered — leaving the existing schedule as-is.")
        return
    prefs_path = d / "options" / "preferences.json"
    prefs = {}
    if prefs_path.exists():
        try:
            prefs = json.loads(prefs_path.read_text())
        except Exception:
            prefs = {}
    existing = prefs.get("schedule_slots_ist", []) or []
    prefs["schedule_slots_ist"] = existing + new_slots
    prefs_path.parent.mkdir(parents=True, exist_ok=True)
    prefs_path.write_text(json.dumps(prefs, indent=2))
    names = ", ".join(f"{s['name']} @ {s['time']}" for s in new_slots)
    print(f"==> Added schedule slot(s): {names}")


def _start(args) -> int:
    d = _data_dir(args.data_dir)
    if args.reconfigure or not _configured(d):
        code = _setup(args)
        if code != 0:
            return code
    else:
        print("==> JobPilot already configured — skipping setup wizard "
             "(pass --reconfigure to redo it).")

    if args.skip_schedule:
        print("==> --skip-schedule passed — leaving the existing schedule as-is.")
    elif not sys.stdin.isatty():
        print("==> Non-interactive session — leaving the existing schedule as-is "
             "(run `jobpilot start` from a terminal to configure schedule slots).")
    else:
        _configure_schedule(d)

    host = args.host or os.environ.get("JOBPILOT_HOST", "127.0.0.1")
    requested_port = args.port or int(os.environ.get("JOBPILOT_PORT", "8787"))
    port = _resolve_port(host, requested_port)
    args.host, args.port = host, port
    url = f"http://{host}:{port}"
    try:
        webbrowser.open(url)
    except Exception:
        pass
    print(f"==> Starting JobPilot service -> {url}")
    return _serve(args)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="jobpilot", description="JobPilot — automated job-hunt pipeline")
    p.add_argument("--version", action="version", version=f"jobpilot {__version__}")
    sub = p.add_subparsers(dest="cmd")

    s = sub.add_parser("setup", help="configure data dir, DB, config, slash commands")
    s.add_argument("--no-wizard", action="store_true", help="skip the interactive secrets wizard")
    s.add_argument("--data-dir", default=None, help="override the data directory")
    s.set_defaults(func=_setup)

    v = sub.add_parser("serve", help="launch the local control service + web UI")
    v.add_argument("--host", default=None)
    v.add_argument("--port", type=int, default=None)
    v.set_defaults(func=_serve)

    d = sub.add_parser("doctor", help="engines/notifiers/sources health check")
    d.add_argument("--live", action="store_true", help="also probe native sources")
    d.set_defaults(func=_doctor)

    w = sub.add_parser("view", help="inspect one doctor item by name")
    w.add_argument("item", help="doctor row name (or unique substring), e.g. Apify")
    w.add_argument("--live", action="store_true", help="also run the live probe for this item")
    w.set_defaults(func=_view)

    t = sub.add_parser("start", help="bootstrap: setup (if needed) -> schedule slots -> serve")
    t.add_argument("--no-wizard", action="store_true", help="skip the interactive secrets wizard")
    t.add_argument("--data-dir", default=None, help="override the data directory")
    t.add_argument("--reconfigure", action="store_true", help="re-run the setup wizard even if already configured")
    t.add_argument("--skip-schedule", action="store_true", help="don't prompt for schedule slots")
    t.add_argument("--host", default=None)
    t.add_argument("--port", type=int, default=None)
    t.set_defaults(func=_start)
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
