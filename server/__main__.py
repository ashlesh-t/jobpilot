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
    from common import find_available_port
    host = os.environ.get("JOBPILOT_HOST", "127.0.0.1")
    requested_port = int(os.environ.get("JOBPILOT_PORT", "8787"))
    port = find_available_port(host, requested_port)
    if port != requested_port:
        print(f"==> Port {requested_port} is already in use — using {port} instead.")
    print(f"JobPilot service → http://{host}:{port}")

    # Publish where we're listening so `jobpilot stop` / `jobpilot start` can find us
    # without guessing a port. Removed on clean shutdown.
    runfile = _write_runfile(host, port)
    try:
        # import the app object via the flat module (server dir is on sys.path)
        from app import app
        uvicorn.run(app, host=host, port=port, log_level="info")
    finally:
        try:
            runfile.unlink(missing_ok=True)
        except OSError:
            pass


def _write_runfile(host: str, port: int):
    import json
    from pathlib import Path as _Path

    raw = os.environ.get("JOBPILOT_DIR", "~/.claude/job-hunt-ai")
    cache = _Path(os.path.expanduser(raw)) / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / "server.json"
    path.write_text(json.dumps({"pid": os.getpid(), "host": host, "port": port}))
    return path


if __name__ == "__main__":
    main()
