import hashlib
import secrets

import httpx
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

MIN_LENGTH = 12
_HIBP_RANGE_URL = "https://api.pwnedpasswords.com/range/"

_hasher = PasswordHasher()


class PasswordPolicyError(Exception):
    """Raised when a candidate password fails the shared password policy."""

    def __init__(self, reasons: list[str]) -> None:
        self.reasons = reasons
        super().__init__("; ".join(reasons))


def hash_password(password: str) -> str:
    """Hash a password with Argon2id."""
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Check a plaintext password against a stored Argon2id hash."""
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def generate_random_password() -> str:
    """A cryptographically random password, used only for bootstrap seeding."""
    return secrets.token_urlsafe(24)


async def validate_password_policy(
    password: str, *, http_client: httpx.AsyncClient | None = None
) -> None:
    # http_client lets callers reuse a connection pool, or tests point at a mocked transport.
    reasons = []

    if len(password) < MIN_LENGTH:
        reasons.append(f"Password must be at least {MIN_LENGTH} characters long.")

    if await _is_pwned(password, http_client=http_client):
        reasons.append("Password has appeared in a known data breach and cannot be used.")

    if reasons:
        raise PasswordPolicyError(reasons)


async def _is_pwned(password: str, *, http_client: httpx.AsyncClient | None = None) -> bool:
    # k-anonymity: only the first 5 hex chars of the SHA-1 hash are sent to HIBP.
    sha1_hex = hashlib.sha1(password.encode("utf-8")).hexdigest().upper()
    prefix, suffix = sha1_hex[:5], sha1_hex[5:]

    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(timeout=5.0)
    try:
        response = await client.get(f"{_HIBP_RANGE_URL}{prefix}")
        response.raise_for_status()
    finally:
        if owns_client:
            await client.aclose()

    for line in response.text.splitlines():
        candidate_suffix, _, _count = line.partition(":")
        if candidate_suffix.strip().upper() == suffix:
            return True
    return False
