"""Install JobPilot as a user-level background service that starts itself.

Linux    → systemd --user unit + `loginctl enable-linger` (starts at boot, survives logout)
macOS    → launchd LaunchAgent with RunAtLoad + KeepAlive
Windows  → Task Scheduler task triggered at logon

The point of the daemon is that scheduled runs happen without anyone opening a terminal:
the machine boots, the service comes up, and the scheduler replays any slot that was
missed while the machine was off (see server/scheduler.py).

Unlike v1 this actually *runs* the enable commands rather than printing them, and can
report status and uninstall again.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
PY = sys.executable or "python3"
PORT = os.environ.get("JOBPILOT_PORT", "8787")
HOST = os.environ.get("JOBPILOT_HOST", "127.0.0.1")

SYSTEMD_UNIT = "jobpilot.service"
LAUNCHD_LABEL = "com.jobpilot.service"
WINDOWS_TASK = "JobPilot"


def _data_dir() -> Path:
    return Path(os.path.expanduser(os.environ.get("JOBPILOT_DIR", "~/.claude/job-hunt-ai")))


def _log_path() -> Path:
    logs = _data_dir() / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    return logs / "server.log"


def _run(cmd: list[str], timeout: int = 60) -> tuple[bool, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return False, str(exc)
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode == 0, out.strip()


# --------------------------------------------------------------------------- #
# Linux — systemd user unit
# --------------------------------------------------------------------------- #
def _systemd_path() -> Path:
    return Path.home() / ".config" / "systemd" / "user" / SYSTEMD_UNIT


def _systemd_unit_text() -> str:
    log = _log_path()
    return f"""[Unit]
Description=JobPilot — local job-hunt service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory={REPO_DIR}
Environment=JOBPILOT_HOST={HOST}
Environment=JOBPILOT_PORT={PORT}
Environment=JOBPILOT_DIR={_data_dir()}
ExecStart={PY} -m server
Restart=on-failure
RestartSec=10
StandardOutput=append:{log}
StandardError=append:{log}

[Install]
WantedBy=default.target
"""


def _install_systemd() -> bool:
    target = _systemd_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_systemd_unit_text())
    print(f"==> Wrote {target}")

    ok, out = _run(["systemctl", "--user", "daemon-reload"])
    if not ok:
        print(f"==> systemctl daemon-reload failed: {out}")
        return False

    # Lingering is what makes the unit start at boot rather than at first login.
    linger_ok, linger_out = _run(["loginctl", "enable-linger", os.environ.get("USER", "")])
    if linger_ok:
        print("==> Enabled lingering — JobPilot will start at boot.")
    else:
        print(f"==> Could not enable lingering ({linger_out.splitlines()[-1] if linger_out else 'unknown'}).")
        print("    JobPilot will start when you log in instead.")

    ok, out = _run(["systemctl", "--user", "enable", "--now", SYSTEMD_UNIT])
    if not ok:
        print(f"==> Failed to enable the service: {out}")
        return False
    print(f"==> Service running → http://{HOST}:{PORT}")
    print(f"==> Logs: {_log_path()}")
    return True


def _uninstall_systemd() -> bool:
    _run(["systemctl", "--user", "disable", "--now", SYSTEMD_UNIT])
    target = _systemd_path()
    if target.exists():
        target.unlink()
        print(f"==> Removed {target}")
    _run(["systemctl", "--user", "daemon-reload"])
    print("==> Service uninstalled. Your data was not touched.")
    return True


def _status_systemd() -> list[str]:
    if not _systemd_path().exists():
        return ["not installed — run `jobpilot service install`"]
    lines = [f"unit: {_systemd_path()}"]
    for prop in ("ActiveState", "UnitFileState"):
        ok, out = _run(["systemctl", "--user", "show", SYSTEMD_UNIT, "-p", prop, "--value"])
        lines.append(f"{prop.lower()}: {out if ok else 'unknown'}")
    ok, out = _run(["loginctl", "show-user", os.environ.get("USER", ""), "-p", "Linger", "--value"])
    lines.append(f"starts at boot: {'yes' if ok and out == 'yes' else 'no (starts at login)'}")
    lines.append(f"logs: {_log_path()}")
    return lines


# --------------------------------------------------------------------------- #
# macOS — launchd
# --------------------------------------------------------------------------- #
def _launchd_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"


def _launchd_plist() -> str:
    log = _log_path()
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>{LAUNCHD_LABEL}</string>
  <key>ProgramArguments</key>
  <array><string>{PY}</string><string>-m</string><string>server</string></array>
  <key>WorkingDirectory</key><string>{REPO_DIR}</string>
  <key>EnvironmentVariables</key><dict>
    <key>JOBPILOT_HOST</key><string>{HOST}</string>
    <key>JOBPILOT_PORT</key><string>{PORT}</string>
    <key>JOBPILOT_DIR</key><string>{_data_dir()}</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>{log}</string>
  <key>StandardErrorPath</key><string>{log}</string>
</dict></plist>
"""


def _install_launchd() -> bool:
    target = _launchd_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_launchd_plist())
    print(f"==> Wrote {target}")
    _run(["launchctl", "unload", str(target)])
    ok, out = _run(["launchctl", "load", "-w", str(target)])
    if not ok:
        print(f"==> launchctl load failed: {out}")
        return False
    print(f"==> Service running → http://{HOST}:{PORT}")
    print(f"==> Logs: {_log_path()}")
    return True


def _uninstall_launchd() -> bool:
    target = _launchd_path()
    if target.exists():
        _run(["launchctl", "unload", "-w", str(target)])
        target.unlink()
        print(f"==> Removed {target}")
    print("==> Service uninstalled. Your data was not touched.")
    return True


def _status_launchd() -> list[str]:
    target = _launchd_path()
    if not target.exists():
        return ["not installed — run `jobpilot service install`"]
    ok, out = _run(["launchctl", "list", LAUNCHD_LABEL])
    return [f"plist: {target}",
            f"loaded: {'yes' if ok else 'no'}",
            f"logs: {_log_path()}"]


# --------------------------------------------------------------------------- #
# Windows — Task Scheduler
# --------------------------------------------------------------------------- #
def _install_windows() -> bool:
    if shutil.which("schtasks") is None:
        print("==> schtasks not found — cannot register a startup task.")
        return False
    command = f'"{PY}" -m server'
    ok, out = _run(["schtasks", "/Create", "/F", "/SC", "ONLOGON",
                    "/TN", WINDOWS_TASK, "/TR", command])
    if not ok:
        print(f"==> Failed to create the task: {out}")
        return False
    print(f"==> Registered scheduled task {WINDOWS_TASK!r} (runs at logon).")
    _run(["schtasks", "/Run", "/TN", WINDOWS_TASK])
    print(f"==> Service running → http://{HOST}:{PORT}")
    return True


def _uninstall_windows() -> bool:
    _run(["schtasks", "/End", "/TN", WINDOWS_TASK])
    ok, out = _run(["schtasks", "/Delete", "/F", "/TN", WINDOWS_TASK])
    print("==> Task removed." if ok else f"==> Could not remove the task: {out}")
    return ok


def _status_windows() -> list[str]:
    ok, out = _run(["schtasks", "/Query", "/TN", WINDOWS_TASK])
    if not ok:
        return ["not installed — run `jobpilot service install`"]
    return [line for line in out.splitlines() if line.strip()][:6]


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def platform_kind() -> str:
    if sys.platform == "darwin":
        return "launchd"
    if sys.platform.startswith("win"):
        return "windows"
    return "systemd"


def install() -> bool:
    kind = platform_kind()
    if kind == "launchd":
        return _install_launchd()
    if kind == "windows":
        return _install_windows()
    if shutil.which("systemctl") is None:
        print("==> systemctl not found — this system doesn't use systemd.")
        print("    Run `jobpilot serve` manually, or add it to your init system.")
        return False
    return _install_systemd()


def uninstall() -> bool:
    kind = platform_kind()
    if kind == "launchd":
        return _uninstall_launchd()
    if kind == "windows":
        return _uninstall_windows()
    return _uninstall_systemd()


def status() -> list[str]:
    kind = platform_kind()
    try:
        if kind == "launchd":
            return _status_launchd()
        if kind == "windows":
            return _status_windows()
        return _status_systemd()
    except Exception as exc:  # noqa: BLE001
        return [f"could not read service status: {exc}"]


def is_installed() -> bool:
    kind = platform_kind()
    if kind == "launchd":
        return _launchd_path().exists()
    if kind == "windows":
        return _run(["schtasks", "/Query", "/TN", WINDOWS_TASK])[0]
    return _systemd_path().exists()


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "install"
    if action == "uninstall":
        raise SystemExit(0 if uninstall() else 1)
    if action == "status":
        for line in status():
            print(line)
        raise SystemExit(0)
    raise SystemExit(0 if install() else 1)
