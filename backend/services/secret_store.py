"""Encrypts users' saved LLM API keys before they are written to the database."""
import base64
import hashlib
import os
from typing import Optional

_PREFIX = "enc:v1:"
_warned = False


def _secret() -> str:
    # ENCRYPTION_KEY is accepted as an alias for servers that already define it.
    return (os.getenv("KEY_ENCRYPTION_SECRET") or os.getenv("ENCRYPTION_KEY") or "").strip()


def encryption_enabled() -> bool:
    return bool(_secret())


def _fernet():
    secret = _secret()
    if not secret:
        return None
    from cryptography.fernet import Fernet
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest()))


def encrypt_secret(value: Optional[str]) -> Optional[str]:
    """Encrypts a key for storage. Without KEY_ENCRYPTION_SECRET the key is stored as is, with a warning."""
    global _warned
    if not value:
        return value
    f = _fernet()
    if f is None:
        if not _warned:
            print("[secret_store] KEY_ENCRYPTION_SECRET is not set: user API keys are stored unencrypted.")
            _warned = True
        return value
    return _PREFIX + f.encrypt(value.encode()).decode()


def decrypt_secret(value: Optional[str]) -> Optional[str]:
    """Returns the plain key. Values stored before encryption was enabled pass through unchanged."""
    if not value or not value.startswith(_PREFIX):
        return value
    f = _fernet()
    if f is None:
        return None
    try:
        return f.decrypt(value[len(_PREFIX):].encode()).decode()
    except Exception:
        return None


def mask_secret(value: Optional[str]) -> dict:
    """What the API may show about a saved key: whether it is set, and its last 4 characters."""
    if not value:
        return {"gemini_api_key_set": False, "gemini_api_key_hint": ""}
    return {"gemini_api_key_set": True, "gemini_api_key_hint": value[-4:] if len(value) > 8 else ""}
