"""The running JobPilot version, resolved the same way from anywhere.

`jobpilot/__init__.py` is the source of truth. The server can't always import that
package directly (it runs with the bundle tree on sys.path), so fall back to installed
distribution metadata before giving up.
"""
from __future__ import annotations

UNKNOWN = "unknown"


def app_version() -> str:
    try:
        from jobpilot import __version__
        return __version__
    except Exception:  # noqa: BLE001
        pass
    try:
        from importlib.metadata import version
        return version("jobpilot-ai")
    except Exception:  # noqa: BLE001
        return UNKNOWN
