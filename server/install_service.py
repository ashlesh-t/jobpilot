"""Install the JobPilot service as a user-level background service.

Linux  → systemd --user unit (~/.config/systemd/user/jobpilot.service)
macOS  → launchd LaunchAgent (~/Library/LaunchAgents/com.jobpilot.service.plist)

Opt-in only — the service also runs fine in the foreground via `python -m server`.
Prints the enable/start commands rather than running privileged actions itself.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
PY = sys.executable or "python3"
PORT = os.environ.get("JOBPILOT_PORT", "8787")


def _systemd_unit() -> str:
    return f"""[Unit]
Description=JobPilot local job-hunt service
After=network-online.target

[Service]
Type=simple
WorkingDirectory={REPO_DIR}
Environment=JOBPILOT_PORT={PORT}
ExecStart={PY} -m server
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
"""


def _launchd_plist() -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.jobpilot.service</string>
  <key>ProgramArguments</key>
  <array><string>{PY}</string><string>-m</string><string>server</string></array>
  <key>WorkingDirectory</key><string>{REPO_DIR}</string>
  <key>EnvironmentVariables</key><dict><key>JOBPILOT_PORT</key><string>{PORT}</string></dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
</dict></plist>
"""


def install() -> None:
    if sys.platform == "darwin":
        target = Path.home() / "Library" / "LaunchAgents" / "com.jobpilot.service.plist"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_launchd_plist())
        print(f"Wrote {target}")
        print("Enable it:\n  launchctl load -w", target)
    else:
        target = Path.home() / ".config" / "systemd" / "user" / "jobpilot.service"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_systemd_unit())
        print(f"Wrote {target}")
        print("Enable it:\n  systemctl --user daemon-reload"
              "\n  systemctl --user enable --now jobpilot.service"
              "\n  (first time, allow lingering so it runs at boot: "
              "loginctl enable-linger $USER)")
    print(f"\nService will serve http://127.0.0.1:{PORT}")


if __name__ == "__main__":
    install()
