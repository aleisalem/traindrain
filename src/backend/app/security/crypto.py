import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import get_settings

_NONCE_BYTES = 12


def encrypt_secret(plaintext: str) -> str:
    """Envelope-encrypt a value (AES-256-GCM) before it's persisted.

    Layered on top of RDS encryption-at-rest per the Release 0 spec — a
    database leak alone still isn't enough to recover a user's TOTP secret;
    the application-layer key (env var locally, Secrets Manager in
    production) is also needed.
    """
    aesgcm = AESGCM(_key())
    nonce = os.urandom(_NONCE_BYTES)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    return base64.b64encode(nonce + ciphertext).decode("ascii")


def decrypt_secret(encrypted: str) -> str:
    aesgcm = AESGCM(_key())
    raw = base64.b64decode(encrypted)
    nonce, ciphertext = raw[:_NONCE_BYTES], raw[_NONCE_BYTES:]
    return aesgcm.decrypt(nonce, ciphertext, None).decode("utf-8")


def _key() -> bytes:
    return base64.b64decode(get_settings().two_factor_encryption_key)
