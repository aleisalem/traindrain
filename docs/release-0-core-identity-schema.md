# Release 0 — Core identity schema

Implements ticket 2 of Release 0 (`.scratch/release-0-foundation/tickets.md`).

## What changed

- Added SQLAlchemy models under `src/backend/app/models`: `User`, `Role` (plus the `user_roles`
  many-to-many join table), `Session`, `AuditLog`.
- Two Alembic migrations: one creates the `users`, `roles`, `user_roles`, `sessions`, and
  `audit_log` tables; the next seeds the three fixed roles (Administrator, Content Manager,
  Learner) and a bootstrap Administrator account. The bootstrap account gets a cryptographically
  random password (`app.security.passwords.generate_random_password`), Argon2id-hashed before
  storage, with `must_change_password` set — the plaintext is written once to application logs
  (`traindrain.bootstrap` logger) and nowhere else, since SES delivery doesn't exist yet.
- Added `src/backend/app/security/passwords.py`: Argon2id hashing (`hash_password`/
  `verify_password`) and the shared password-policy validator (`validate_password_policy`) —
  rejects passwords under 12 characters and any password found via the HIBP Pwned Passwords API
  (k-anonymity; only the first 5 hex characters of the SHA-1 hash are sent). Both the forced
  first-login change (ticket 3) and invite acceptance (ticket 5) will reuse this validator.
- Added `src/backend/app/security/audit.py`: `record_audit_log`, a small helper that writes
  `actor_user_id`, `action`, `target_user_id`, `timestamp`, and a JSON `detail` blob. It flushes
  but doesn't commit, so callers can fold an audit entry into a larger transaction.
- Added `bootstrap_admin_email` to `app.core.config.Settings` (default `admin@traindrain.local`,
  overridable via env var) — the address the bootstrap account is seeded under.
- `users.email` has a case-insensitive unique index (on `lower(email)`, alongside a plain index
  for exact-match lookups) — email is the username and invite-targeting key (PRD), so two accounts
  differing only by case would otherwise be able to coexist.
- `audit_log.actor_user_id` is `NOT NULL` — every action the PRD lists as audit-logged (invites,
  role changes, disable/enable/erase, 2FA admin-reset, group changes) is admin-initiated.
- Added real-database test infrastructure: `tests/conftest.py` now runs Alembic migrations once
  per test session and exposes a `db_session` fixture (transaction rolled back per test), per the
  project's "test against a real Postgres" decision. Fixed the default `DATABASE_URL` in
  `conftest.py` to match `docker-compose`'s Postgres (port 5433), and pinned
  `asyncio_default_fixture_loop_scope`/`asyncio_default_test_loop_scope` to `"session"` in
  `pyproject.toml` — required so pooled asyncpg connections don't get torn across event loops
  when multiple async tests share the module-level `app.db.engine`.

## Notes

- `httpx` moved from a dev-only dependency to a runtime one (the HIBP check needs it outside of
  tests); `argon2-cffi` was added as a new runtime dependency.
- No endpoints exist yet — login, session lifecycle, and the forced-password-change gate are
  ticket 3. This ticket is schema plus independently-testable utilities only.
