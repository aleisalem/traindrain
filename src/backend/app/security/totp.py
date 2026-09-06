import base64
import io
import secrets

import pyotp
import qrcode

from app.security.crypto import decrypt_secret

ISSUER = "TrainDrain"
RECOVERY_CODE_COUNT = 10


def generate_totp_secret() -> str:
    """A fresh base32 TOTP secret, per RFC 6238 — encrypt before storing."""
    return pyotp.random_base32()


def provisioning_uri(secret: str, *, account_email: str) -> str:
    """The otpauth:// URI an authenticator app scans (as a QR code)."""
    return pyotp.TOTP(secret).provisioning_uri(name=account_email, issuer_name=ISSUER)


def qr_code_data_uri(uri: str) -> str:
    """Render a provisioning URI as a scannable QR code PNG, base64-inlined."""
    image = qrcode.make(uri)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def verify_totp_code(encrypted_secret: str, code: str) -> bool:
    """Check a candidate code against an encrypted-at-rest secret.

    valid_window=1 tolerates one 30s step of clock drift either side, the
    same allowance most authenticator-app integrations make.
    """
    secret = decrypt_secret(encrypted_secret)
    return pyotp.TOTP(secret).verify(code.strip(), valid_window=1)


def generate_recovery_codes(count: int = RECOVERY_CODE_COUNT) -> list[str]:
    """~10 single-use backup codes, formatted for easy transcription."""
    return [_format_recovery_code(secrets.token_hex(5)) for _ in range(count)]


def _format_recovery_code(raw_hex: str) -> str:
    upper = raw_hex.upper()
    return f"{upper[:5]}-{upper[5:]}"
