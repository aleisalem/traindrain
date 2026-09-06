import hashlib
import secrets

TOKEN_BYTES = 32


def generate_token() -> str:
    """A cryptographically random, URL-safe opaque token (session/invite/reset tokens)."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(token: str) -> str:
    """Deterministically hash an opaque token for storage/lookup.

    Unlike passwords, these tokens are already high-entropy and looked up by
    exact match, so a fast deterministic hash (not Argon2id's salted hash) is
    used — a DB leak alone still can't be used to reconstruct or reuse the token.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
