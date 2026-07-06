"""`jobpilot` console entry point — cross-platform (Linux/macOS/Windows).

Subcommands:
  jobpilot setup     configure the data dir, DB, config, slash commands (stdlib only)
  jobpilot serve     launch the local control service + web UI (needs the [server] extra)
  jobpilot doctor    print an engines/notifiers/sources health table
  jobpilot --version

Each subcommand runs against the bundled runtime tree resolved by jobpilot.paths, so the
same command works from a pipx install or a git checkout.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

from . import __version__
from .paths import bundle_root, runtime_env


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
    if args.port:
        env["JOBPILOT_PORT"] = str(args.port)
    if args.host:
        env["JOBPILOT_HOST"] = args.host
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
