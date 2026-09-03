# Release 0 — Two-factor authentication (setup, login, recovery)

Implements tickets 7 and 8 of Release 0 (`.scratch/release-0-foundation/tickets.md`).

## What changed

- New tables: `two_factor_credentials` (one row per user, envelope-encrypted
  TOTP secret via AES-256-GCM — `app/security/crypto.py`, key from
  `TWO_FACTOR_ENCRYPTION_KEY` — and an `enabled_at` that stays null until a
  real code confirms enrollment), `recovery_codes` (Argon2id-hashed,
  single-use, ~10 issued on enable), and `two_factor_challenges` (a
  short-lived, httpOnly-cookie-referenced bridge between "password verified"
  and "second factor verified").
- `POST /api/auth/2fa/enroll`: generates a TOTP secret, returns a QR code
  (`app/security/totp.py`) and setup key. `POST /api/auth/2fa/enable`:
  confirms enrollment with a real TOTP code, issues the recovery codes
  (shown once), and invalidates the user's other active sessions — enabling
  2FA is a security-posture change, same treatment as a password change.
- Login (`POST /api/auth/login`) now checks for an enabled credential: if
  present, password success sets a 5-minute 2FA-challenge cookie and returns
  `two_factor_required: true` instead of a session. `POST /api/auth/2fa/verify`
  accepts either a TOTP code or an unused recovery code (sharing the login
  endpoint's rate-limit budget, since a 6-digit code is brute-forceable) and
  only then issues the real session.
- `POST /api/auth/2fa/disable`: a user can disable their own 2FA, confirmed
  with their current password. `POST /api/admin/users/2fa/disable`
  (`require_administrator`, target identified by email since there's no
  user-listing endpoint yet) covers the case where a user has lost both
  their authenticator and their recovery codes; it's audit-logged
  (`two_factor_admin_disabled`). Both paths delete the credential and any
  remaining recovery codes and invalidate other active sessions for the
  affected account — a self-disable keeps the caller's own session, an
  admin-disable has none of the target's sessions to spare.
- Frontend: `features/twoFactor/TwoFactorSettings.tsx` (dashboard
  enroll/enable/disable flow), `features/auth/TwoFactorVerifyForm.tsx`
  (login-time second step), and `features/admin/AdminDisableTwoFactorPage.tsx`
  (`/admin/two-factor`, admin recovery UI) — all with English/German copy.

## Notes

- Verified end-to-end against the real local stack (rebuilt the backend
  image, drove enroll → enable → self-disable and enroll → enable →
  admin-disable through the live API), confirming session invalidation and
  the admin-disable audit-log row land correctly outside the pytest
  fixtures' isolated transactions.
- No frontend user-listing page exists yet (that's ticket 9), so the admin
  disable UI identifies the target account by email rather than by id.
