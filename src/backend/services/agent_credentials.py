from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from config import settings


def _fernet() -> Fernet:
    secret = (settings.AGENT_API_KEY_ENCRYPTION_SECRET or settings.SECRET_KEY).encode("utf-8")
    digest = hashlib.sha256(secret).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def encrypt_api_key(api_key: str) -> str:
    value = (api_key or "").strip()
    if not value:
        raise ValueError("API Key cannot be empty")
    return _fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_api_key(encrypted_api_key: str | None) -> str | None:
    if not encrypted_api_key:
        return None
    try:
        return _fernet().decrypt(encrypted_api_key.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("Stored API Key cannot be decrypted") from exc
