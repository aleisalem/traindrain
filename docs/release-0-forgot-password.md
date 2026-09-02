# Release 0 — Forgot-password flow

Implements ticket 6 of Release 0 (`.scratch/release-0-foundation/tickets.md`).

## What changed

- New table: `password_reset_tokens` (single-use, hashed token — same pattern
  as sessions/invites — plus `user_id`, `expires_at`, `used_at`).
- `POST /api/auth/forgot-password`: accepts an email and always returns 204,
  whether or not it matches an account — the response never leaks account
  existence. For a matching account, supersedes any still-pending reset token
  for that user (the same "a fresh request invalidates the prior one" pattern
  as re-inviting), issues a new token with a 1-hour expiry, and emails it via
  the same SES/LocalStack-SES path invites use, in the user's
  `preferred_language`. Only committed once the send succeeds, so a failed
  send leaves no half-issued token behind.
- `POST /api/auth/reset-password`: validates the token (exists, unused, not
  expired — 410 "no longer valid" otherwise, identical for every reason so a
  caller can't distinguish them), enforces the ticket 2 password-policy
  validator (422 on violation), sets the new password, clears
  `must_change_password`, and invalidates all of the user's other active
  sessions (`revoke_other_sessions` with no session to keep, since the caller
  isn't authenticated).
- `app/security/mailer.py` gained `send_password_reset_email`, a plain-text
  EN/DE reset email built the same way as the invite email, reusing the
  shared `_send` helper both now go through.
- Frontend: `features/auth/ForgotPasswordPage.tsx` (email form, POSTs to
  `/api/auth/forgot-password`, always shows the same "check your email"
  confirmation — including on a network error — so the UI can't leak account
  existence either) and `features/auth/ResetPasswordPage.tsx` (reads `token`
  from the query string, collects and confirms a new password, handles the
  410/422 cases). Both are reachable at `/forgot-password` and
  `/reset-password` regardless of session state, the same way
  `/accept-invite` is. `LoginForm` gained a "Forgot your password?" link.

## Notes

- Verified against the real local stack: rebuilt the backend image, called
  `/api/auth/forgot-password` for the bootstrap admin, confirmed LocalStack's
  SES emulation (`GET /_aws/ses`) received the right subject/body/link,
  walked the token through `/api/auth/reset-password`, and confirmed login
  with the new password succeeds while the token is now rejected (410) on
  reuse.
- Found and fixed a real pre-existing bug while validating this: the shared
  `db_session` pytest fixture (`tests/conftest.py`) claimed to roll back
  after each test, but without SQLAlchemy's
  `join_transaction_mode="create_savepoint"`, a route's `db.commit()`
  actually committed straight through the fixture's outer transaction to the
  real local dev Postgres — the same instance `docker-compose`'s backend
  container uses. Running the suite had been silently corrupting the seeded
  bootstrap admin's password/`must_change_password` and leaving stray rows
  behind. Fixed by passing `join_transaction_mode="create_savepoint"` when
  constructing the fixture's session, and reset the local `postgres_data`
  docker volume to a clean, freshly-seeded state. Verified by running the
  full suite twice in a row and confirming row counts return to baseline
  after each run.
- No separate "check if this token is still valid" endpoint before the reset
  form loads (unlike the invite flow's `GET /api/invites/{token}`) — the
  ticket only calls for a request-reset and a reset endpoint, so the reset
  page just attempts the reset directly and shows the same "no longer valid"
  screen if the backend returns 410.
