"""The one instance-wide encryption key, used to encrypt every row in `user_secrets`.

Per-user credentials (Apify token, Telegram bot token, ...) are encrypted at rest in
Postgres/SQLite (see core/secrets.py) rather than living in the OS keyring, since the
keyring is host-wide and doesn't map to individual accounts on a shared instance. The
key that encrypts them, however, is exactly the kind of machine-level secret the
keyring is for — one Fernet key, generated once, never sent to a browser.
"""
from __future__ import annotations

import os
from pathlib import Path

from cryptography.fernet import Fernet

from .paths import jobpilot_dir

KEYRING_SERVICE = "jobpilot-instance"
KEYRING_KEY = "master_encryption_key"

_cached_key: bytes | None = None


def _key_file_path() -> Path:
    return jobpilot_dir() / "cache" / ".master_key"


def get_or_create_master_key() -> bytes:
    """Return the instance's Fernet key, creating it on first use.

    Tries the OS keyring first; falls back to a 0600-permissioned file under the data
    directory, matching scripts/jp_secrets.py's own keyring-then-file fallback shape.
    """
    global _cached_key
    if _cached_key is not None:
        return _cached_key

    env_key = os.environ.get("JOBPILOT_MASTER_KEY")
    if env_key:
        _cached_key = env_key.encode("utf-8")
        return _cached_key

    try:
        import keyring

        existing = keyring.get_password(KEYRING_SERVICE, KEYRING_KEY)
        if existing:
            _cached_key = existing.encode("utf-8")
            return _cached_key
        new_key = Fernet.generate_key()
        keyring.set_password(KEYRING_SERVICE, KEYRING_KEY, new_key.decode("utf-8"))
        _cached_key = new_key
        return _cached_key
    except Exception:
        pass

    key_path = _key_file_path()
    if key_path.is_file():
        _cached_key = key_path.read_bytes().strip()
        return _cached_key

    key_path.parent.mkdir(parents=True, exist_ok=True)
    new_key = Fernet.generate_key()
    key_path.write_bytes(new_key)
    key_path.chmod(0o600)
    _cached_key = new_key
    return _cached_key


def _fernet() -> Fernet:
    return Fernet(get_or_create_master_key())


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt(ciphertext: str) -> str:
    return _fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
