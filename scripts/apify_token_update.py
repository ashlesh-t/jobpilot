"""Minimal Apify token updater — update one token slot without re-running full setup.

Usage:
  python3 scripts/apify_token_update.py           # prompts for slot, defaults to 1
  python3 scripts/apify_token_update.py --slot 2  # update slot 2 (APIFY_TOKEN_2)
  python3 scripts/apify_token_update.py --status  # show current slot status
"""
from __future__ import annotations

import getpass
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from secrets import get_secret_optional, set_secret  # noqa: E402

import requests

APIFY_BASE = "https://api.apify.com/v2"

SLOT_KEYS = {1: "APIFY_TOKEN", 2: "APIFY_TOKEN_2", 3: "APIFY_TOKEN_3"}


def _validate(token: str) -> str:
    """Returns Apify username on success, raises ValueError on failure."""
    resp = requests.get(
        f"{APIFY_BASE}/users/me",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    if resp.status_code != 200:
        raise ValueError(f"HTTP {resp.status_code}")
    data = resp.json().get("data", {})
    username = data.get("username") or data.get("id") or "unknown"
    return username


def _jobpilot_dir() -> Path:
    import os
    raw = os.environ.get("JOBPILOT_DIR", "~/.claude/job-hunt-ai")
    return Path(os.path.expanduser(raw))


def _clear_exhausted_slot(slot: int) -> None:
    state_path = _jobpilot_dir() / "cache" / "run_state.json"
    try:
        state = json.loads(state_path.read_text())
        exhausted = [s for s in state.get("exhausted_slots", []) if s != slot]
        state["exhausted_slots"] = exhausted
        state_path.write_text(json.dumps(state, indent=2))
    except Exception:
        pass  # state file may not exist yet — that's fine


def show_status() -> None:
    print("\nApify token slot status:")
    for slot, key in SLOT_KEYS.items():
        token = get_secret_optional(key)
        if not token:
            print(f"  Slot {slot} ({key}): MISSING")
            continue
        try:
            username = _validate(token)
            print(f"  Slot {slot} ({key}): VALID  (account: {username})")
        except Exception as exc:
            print(f"  Slot {slot} ({key}): INVALID  ({exc})")
    print()


def update_slot(slot: int) -> None:
    key = SLOT_KEYS[slot]
    print(f"\nUpdating Apify token slot {slot} ({key})")
    print("Get your token at: https://console.apify.com/account/integrations")
    print()
    token = getpass.getpass(f"Paste new APIFY token for slot {slot} (input hidden): ").strip()
    if not token:
        print("No token entered — aborted.")
        sys.exit(1)
    print("Validating token...", end=" ", flush=True)
    try:
        username = _validate(token)
        print(f"valid (account: {username})")
    except Exception as exc:
        print(f"INVALID: {exc}")
        print("Token not saved.")
        sys.exit(1)
    backend = set_secret(key, token)
    print(f"Token saved to {backend}.")
    _clear_exhausted_slot(slot)
    print(f"Slot {slot} cleared from exhausted list.")
    print(f"\nSlot {slot} ready. Full Apify runs will resume on next /job-search call.")


def main() -> None:
    args = sys.argv[1:]

    if "--status" in args:
        show_status()
        return

    slot = 1
    if "--slot" in args:
        idx = args.index("--slot")
        if idx + 1 < len(args):
            try:
                slot = int(args[idx + 1])
            except ValueError:
                print("--slot must be 1, 2, or 3")
                sys.exit(1)

    if slot not in SLOT_KEYS:
        print(f"Invalid slot {slot}. Use 1, 2, or 3.")
        sys.exit(1)

    update_slot(slot)


if __name__ == "__main__":
    main()
