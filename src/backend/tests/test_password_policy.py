import hashlib

import httpx
import pytest

from app.security.passwords import (
    MIN_LENGTH,
    PasswordPolicyError,
    generate_random_password,
    hash_password,
    validate_password_policy,
    verify_password,
)


def _hibp_client(pwned_suffixes: dict[str, int] | None = None) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        body = "\n".join(f"{suffix}:{count}" for suffix, count in (pwned_suffixes or {}).items())
        return httpx.Response(200, text=body)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_rejects_password_under_minimum_length() -> None:
    client = _hibp_client()
    try:
        with pytest.raises(PasswordPolicyError) as exc_info:
            await validate_password_policy("short1234", http_client=client)
    finally:
        await client.aclose()

    assert any("12 characters" in reason for reason in exc_info.value.reasons)


async def test_accepts_long_unbreached_password() -> None:
    client = _hibp_client()
    try:
        await validate_password_policy("a-perfectly-fine-passphrase", http_client=client)
    finally:
        await client.aclose()


async def test_rejects_password_found_in_breach() -> None:
    password = "correct horse battery staple 42"
    sha1_hex = hashlib.sha1(password.encode("utf-8")).hexdigest().upper()
    suffix = sha1_hex[5:]

    client = _hibp_client({suffix: 123})
    try:
        with pytest.raises(PasswordPolicyError) as exc_info:
            await validate_password_policy(password, http_client=client)
    finally:
        await client.aclose()

    assert any("breach" in reason for reason in exc_info.value.reasons)


async def test_only_sends_hash_prefix_to_hibp() -> None:
    password = "a-perfectly-fine-passphrase"
    sha1_hex = hashlib.sha1(password.encode("utf-8")).hexdigest().upper()
    seen_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        return httpx.Response(200, text="")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        await validate_password_policy(password, http_client=client)
    finally:
        await client.aclose()

    assert len(seen_paths) == 1
    sent_prefix = seen_paths[0].rsplit("/", 1)[-1]
    assert sent_prefix == sha1_hex[:5]
    assert len(sent_prefix) == 5


def test_generated_password_meets_minimum_length() -> None:
    assert len(generate_random_password()) >= MIN_LENGTH


def test_generated_passwords_are_not_reused() -> None:
    assert generate_random_password() != generate_random_password()


def test_hash_and_verify_round_trip() -> None:
    password = "a-perfectly-fine-passphrase"
    password_hash = hash_password(password)

    assert password_hash != password
    assert verify_password(password, password_hash) is True
    assert verify_password("wrong-password", password_hash) is False
