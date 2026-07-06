"""Entry point: `python -m server` — start the local JobPilot service.

Env overrides: JOBPILOT_HOST (default 127.0.0.1), JOBPILOT_PORT (default 8787).
Sub-command: `python -m server install-service` writes a systemd/launchd unit.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "install-service":
        from install_service import install
        install()
        return

    import uvicorn
    host = os.environ.get("JOBPILOT_HOST", "127.0.0.1")
    port = int(os.environ.get("JOBPILOT_PORT", "8787"))
    print(f"JobPilot service → http://{host}:{port}")
    # import the app object via the flat module (server dir is on sys.path)
    from app import app
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
