"""Telegram OTP web flow — makes `--auth` friendly (phone + OTP in the browser).

Splits the Telethon interactive login into three request/response steps, holding the
transient client in server memory keyed by a short-lived token. The session lands at the
SAME path the scraper reads (cache/telegram.session), so telegram_channels.fetch() picks
it up unchanged.

telethon is imported lazily — the endpoints degrade with a clear message if it's absent.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

from common import jobpilot_dir  # noqa: E402


def _session_path() -> Path:
    raw = os.environ.get("JOBPILOT_DIR", "~/.claude/job-hunt-ai")
    return Path(os.path.expanduser(raw)) / "cache" / "telegram"


def _api_creds():
    from jp_secrets import get_secret_optional  # noqa
    api_id = get_secret_optional("TELEGRAM_API_ID")
    api_hash = get_secret_optional("TELEGRAM_API_HASH")
    return (int(api_id) if api_id else None), api_hash


class TelegramAuth:
    """In-memory registry of pending logins, keyed by an opaque token."""

    def __init__(self):
        self._pending: dict[str, dict] = {}

    def status(self) -> dict:
        api_id, api_hash = _api_creds()
        return {
            "telethon_installed": self._telethon_ok(),
            "api_creds_set": bool(api_id and api_hash),
            "session_exists": _session_path().with_suffix(".session").exists(),
        }

    @staticmethod
    def _telethon_ok() -> bool:
        try:
            import telethon  # noqa
            return True
        except Exception:
            return False

    async def start(self, phone: str) -> dict:
        if not self._telethon_ok():
            return {"ok": False, "error": "telethon not installed (pip install telethon)"}
        api_id, api_hash = _api_creds()
        if not (api_id and api_hash):
            return {"ok": False, "error": "TELEGRAM_API_ID / TELEGRAM_API_HASH not set"}
        from telethon import TelegramClient  # noqa

        client = TelegramClient(str(_session_path()), api_id, api_hash)
        await client.connect()
        if await client.is_user_authorized():
            me = await client.get_me()
            await client.disconnect()
            return {"ok": True, "already": True,
                    "username": getattr(me, "username", "") or getattr(me, "first_name", "")}
        try:
            sent = await client.send_code_request(phone)
        except Exception as exc:  # noqa: BLE001
            await client.disconnect()
            return {"ok": False, "error": f"send_code_request failed: {exc}"}
        token = uuid.uuid4().hex
        self._pending[token] = {"client": client, "phone": phone,
                                "hash": sent.phone_code_hash}
        return {"ok": True, "token": token}

    async def submit_code(self, token: str, code: str) -> dict:
        ctx = self._pending.get(token)
        if not ctx:
            return {"ok": False, "error": "unknown or expired token — restart auth"}
        client = ctx["client"]
        try:
            from telethon.errors import SessionPasswordNeededError  # noqa
        except Exception:
            SessionPasswordNeededError = Exception  # type: ignore
        try:
            await client.sign_in(ctx["phone"], code, phone_code_hash=ctx["hash"])
        except SessionPasswordNeededError:
            return {"ok": True, "need_password": True}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"sign_in failed: {exc}"}
        return await self._finish(token)

    async def submit_password(self, token: str, password: str) -> dict:
        ctx = self._pending.get(token)
        if not ctx:
            return {"ok": False, "error": "unknown or expired token — restart auth"}
        client = ctx["client"]
        try:
            await client.sign_in(password=password)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"2FA sign_in failed: {exc}"}
        return await self._finish(token)

    async def _finish(self, token: str) -> dict:
        ctx = self._pending.pop(token, None)
        if not ctx:
            return {"ok": False, "error": "session lost"}
        client = ctx["client"]
        try:
            me = await client.get_me()
            username = getattr(me, "username", "") or getattr(me, "first_name", "")
        except Exception:
            username = ""
        finally:
            await client.disconnect()  # session file is now written
        return {"ok": True, "connected": True, "username": username}


tg_auth = TelegramAuth()
