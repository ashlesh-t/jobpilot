"""Ephemeral profile-review launcher.

`/job-setup` Step F calls this after Claude drafts `profile.json`, so the user can
review/edit the full structured profile in a browser before it's marked
`profile_verified: true`. If a persistent `jobpilot serve` is already running on the
configured host/port, its `/profile-review` page is reused. Otherwise a throw-away
uvicorn instance is started on an OS-assigned free port, used for the review, and
torn down afterward — no orphan process left listening.

Usage:
    python3 -m server.ephemeral [--timeout SECONDS]

Prints exactly one line to stdout — "done", "skipped", or "timeout" — and always
exits 0: the review is an enhancement, never a hard gate on `/job-setup` completing.
"""
from __future__ import annotations

import argparse
import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import httpx  # noqa: E402
import uvicorn  # noqa: E402

from common import profile_review_done_path  # noqa: E402

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787
DEFAULT_TIMEOUT_S = 600.0


def _free_port(host: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return s.getsockname()[1]


def _is_alive(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        r = httpx.get(f"http://{host}:{port}/health", timeout=timeout)
        return r.status_code == 200
    except Exception:
        return False


def _wait_ready(host: str, port: int, timeout_s: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if _is_alive(host, port, timeout=0.5):
            return True
        time.sleep(0.2)
    return False


def _poll_done(host: str, port: int, timeout_s: float) -> str:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            r = httpx.get(f"http://{host}:{port}/api/profile/done", timeout=2.0)
            if r.status_code == 200 and r.json().get("done"):
                return "done"
        except Exception:
            pass
        time.sleep(1.0)
    return "timeout"


def _clear_done_flag(host: str, port: int) -> None:
    try:
        httpx.post(f"http://{host}:{port}/api/profile/done", json={"done": False}, timeout=2.0)
    except Exception:
        pass


def run_profile_review_and_wait(timeout_s: float = DEFAULT_TIMEOUT_S) -> str:
    """Open the profile review page and block until the user finishes or times out.

    Returns "done", "skipped" (server/browser could not be reached), or "timeout".
    """
    host = os.environ.get("JOBPILOT_HOST", DEFAULT_HOST)
    configured_port = int(os.environ.get("JOBPILOT_PORT", str(DEFAULT_PORT)))

    if _is_alive(host, configured_port):
        _clear_done_flag(host, configured_port)
        profile_review_done_path().unlink(missing_ok=True)
        url = f"http://{host}:{configured_port}/profile-review"
        try:
            webbrowser.open(url)
        except Exception:
            return "skipped"
        return _poll_done(host, configured_port, timeout_s)

    # No persistent server — start a throw-away instance on a free port.
    port = _free_port(host)
    from app import app  # imported after sys.path wiring above

    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        if not _wait_ready(host, port, timeout_s=10.0):
            return "skipped"
        profile_review_done_path().unlink(missing_ok=True)
        url = f"http://{host}:{port}/profile-review"
        try:
            webbrowser.open(url)
        except Exception:
            return "skipped"
        return _poll_done(host, port, timeout_s)
    finally:
        server.should_exit = True
        thread.join(timeout=10.0)


def main() -> None:
    parser = argparse.ArgumentParser(description="Launch the profile review page and wait for the user.")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S,
                       help="seconds to wait before giving up (default: %(default)s)")
    args = parser.parse_args()
    result = run_profile_review_and_wait(timeout_s=args.timeout)
    print(result)


if __name__ == "__main__":
    main()
