"""Cross-platform JobPilot setup — pure stdlib, no third-party deps.

Replaces the bash `setup.sh` so Windows/macOS/Linux all use the identical command:
initialises the data directory, copies default config, creates the SQLite cache via the
stdlib `sqlite3` module (no external `sqlite3` CLI needed — the key Windows win), seeds the
lessons cache, syncs slash commands, and optionally installs deps + runs the secrets wizard.

Run directly (`python3 scripts/jobpilot_setup.py`), via `setup.sh` (a thin shim), or as the
`jobpilot setup` CLI subcommand. Idempotent — safe to re-run.

Flags:
  --no-deps     skip `pip install -r requirements.txt` (e.g. when installed via pipx)
  --no-wizard   skip the interactive secrets wizard (CI / non-interactive)
  --data-dir P  override the data directory (else $JOBPILOT_DIR or ~/.claude/job-hunt-ai)
"""
from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent


def data_dir(override: str | None = None) -> Path:
    if override:
        return Path(os.path.expanduser(override))
    raw = os.environ.get("JOBPILOT_DIR", "~/.claude/job-hunt-ai")
    return Path(os.path.expanduser(raw))


def _log(msg: str) -> None:
    print(f"==> {msg}")


def _warn(msg: str) -> None:
    print(f"!!  {msg}", file=sys.stderr)


def make_dirs(d: Path) -> None:
    for sub in ("options", "resumes/tailored", "cache", "reports"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    _log(f"Data directories ready under {d}")


def copy_if_absent(src: Path, dst: Path, label: str) -> None:
    if dst.exists():
        _log(f"{label} already exists — leaving it untouched")
        return
    if not src.exists():
        _warn(f"{label}: template {src} missing — skipped")
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(src, dst)
    _log(f"Installed default {label}")


def init_db(d: Path) -> None:
    db = d / "cache" / "jobs.sqlite"
    schema = REPO_DIR / "schema" / "init.sql"
    if not schema.exists():
        _warn(f"schema not found at {schema} — skipping DB init")
        return
    conn = sqlite3.connect(str(db))
    try:
        conn.executescript(schema.read_text())
        conn.commit()
    finally:
        conn.close()
    _log(f"Initialised SQLite cache at {db}")


def sync_commands() -> None:
    """Copy each skills/<name>/SKILL.md to .claude/commands/<name>.md in the repo."""
    commands = REPO_DIR / ".claude" / "commands"
    commands.mkdir(parents=True, exist_ok=True)
    skills = REPO_DIR / "skills"
    if not skills.exists():
        return
    for skill_dir in sorted(skills.iterdir()):
        skill_md = skill_dir / "SKILL.md"
        if skill_dir.is_dir() and skill_md.exists():
            shutil.copy(skill_md, commands / f"{skill_dir.name}.md")
    _log("Slash commands synced to .claude/commands/")


def ensure_local_settings() -> None:
    p = REPO_DIR / ".claude" / "settings.local.json"
    if p.exists():
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        '{\n  "permissions": {\n    "allow": [],\n'
        '    "_note": "MCP tool permissions (Drive, etc.) are auto-populated by '
        '/job-setup Step H."\n  }\n}\n'
    )
    _log("Created .claude/settings.local.json")


def install_deps() -> None:
    req = REPO_DIR / "requirements.txt"
    if not req.exists():
        return
    try:
        subprocess.run([sys.executable, "-m", "pip", "install", "-r", str(req)], check=True)
        _log("Installed core Python dependencies")
    except Exception as exc:  # noqa: BLE001
        _warn(f"pip install failed ({exc}). Run manually: pip install -r requirements.txt")


def run_wizard() -> None:
    wiz = REPO_DIR / "scripts" / "setup_wizard.py"
    if not wiz.exists():
        return
    if not sys.stdin.isatty():
        _log("Non-interactive — skipping secrets wizard "
             "(run `python3 scripts/setup_wizard.py` later)")
        return
    _log("Launching secrets wizard...")
    subprocess.run([sys.executable, str(wiz)])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="jobpilot-setup", description="Configure JobPilot")
    ap.add_argument("--no-deps", action="store_true", help="skip pip install")
    ap.add_argument("--no-wizard", action="store_true", help="skip the secrets wizard")
    ap.add_argument("--data-dir", default=None, help="override data directory")
    args = ap.parse_args(argv)

    d = data_dir(args.data_dir)
    print("==> JobPilot setup starting")
    print(f"    Repo:     {REPO_DIR}")
    print(f"    Data dir: {d}")

    make_dirs(d)
    copy_if_absent(REPO_DIR / "config" / "preferences.example.json",
                   d / "options" / "preferences.json", "preferences.json")
    init_db(d)
    copy_if_absent(REPO_DIR / "config" / "apify_lessons_seed.json",
                   d / "cache" / "apify_lessons.json", "apify_lessons.json")
    sync_commands()
    ensure_local_settings()
    if not args.no_deps:
        install_deps()
    if not args.no_wizard:
        run_wizard()

    print("\n==> JobPilot setup complete.")
    print("    Next: connect the Claude Code plugin, then run /job-setup in Claude.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
