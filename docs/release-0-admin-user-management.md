# Release 0 — Admin user management: list, disable, enable, erase

Implements ticket 9 of Release 0 (`.scratch/release-0-foundation/tickets.md`).

## What changed

- `users` gained two nullable timestamp columns: `disabled_at` and
  `erased_at` (migration `6c0140842509`).
- `GET /api/admin/users`: lists every user (email, name, roles, `disabled_at`,
  `erased_at`, `created_at`), Administrator-only.
- `POST /api/admin/users/{user_id}/disable`: soft, reversible — sets
  `disabled_at`, revokes every one of the target's active sessions, and
  blocks future login (both `POST /api/auth/login` and the
  `POST /api/auth/2fa/verify` second-factor step treat a disabled account the
  same way they treat wrong credentials, so a caller can't distinguish
  "disabled" from "wrong password/code" — same reasoning as the existing
  unknown-email path). `require_active_user`/`get_current_user` also reject a
  disabled account's session directly, as defense in depth against a session
  that outlives the revocation for any reason. 409 if already disabled; an
  admin can't disable their own account (self-lockout guard, not in the
  original ticket text but a cheap, obviously-desirable safety net).
- `POST /api/admin/users/{user_id}/enable`: clears `disabled_at`, restoring
  login. 409 if not disabled, or if the account has been erased (erasure is
  permanent — enable never applies to it).
- `POST /api/admin/users/{user_id}/erase`: hard, GDPR right-to-erasure.
  Anonymizes `email` (replaced with a per-user, deterministic
  `erased-user-{id}@erased.invalid` tombstone address — unique without
  needing to check for collisions), clears `first_name`/`last_name`,
  replaces `password_hash` with one derived from a random, discarded value,
  and sets both `erased_at` and `disabled_at`. The row itself is kept (not
  deleted) so `audit_log.target_user_id` and future foreign keys keep
  resolving. 409 if already erased; an admin can't erase their own account.
  Deliberately does **not** write the pre-erasure email (or any other
  personal field) into the audit-log `detail` blob — logging the erased data
  right back into a permanent record would defeat the point of the request;
  `target_user_id` is enough to trace which tombstone the action touched.
- All three mutating actions call `record_audit_log` (`user_disabled`,
  `user_enabled`, `user_erased`); `GET /api/admin/users` is a read and isn't
  audit-logged, consistent with every other read endpoint in the admin API
  (e.g. `GET /api/admin/roles`).
- Frontend: `features/admin/AdminUsersPage.tsx` (`/admin/users`, linked from
  `AdminShell` as "Manage users") — a table with per-row Disable/Enable/Erase
  actions. Erase requires a second "Confirm erase" click (a UX safeguard for
  an irreversible action, mirroring the confirm/cancel pattern already used
  by the self-service 2FA-disable flow). The admin's own row shows neither
  action, matching the backend's self-lockout guard.

## Notes

- Verified against the real local stack: rebuilt the backend image (a stale
  cached image had missed the new migration file, which surfaced as
  `alembic.util.messaging.CommandError: Can't locate revision`), seeded a
  couple of throwaway Learner accounts directly in Postgres, and drove the
  full list → disable → enable → erase flow through a headless browser
  against the Vite dev server, in both light and dark themes. Confirmed via
  `psql` that an erased row's `email`/`disabled_at`/`erased_at` land exactly
  as expected, and that the row survives (rather than violating the
  `audit_log` foreign key). Test data was cleaned up afterward; the bootstrap
  Administrator's password was overwritten with a known value for the
  session and no longer matches whatever was in the original backend logs.
- A code-review pass surfaced a real gap this ticket introduced: the 2FA
  second-factor endpoint (`POST /api/auth/2fa/verify`) didn't check
  `disabled_at`, so a user disabled mid-way through an in-flight 2FA
  challenge (the challenge cookie lives up to 5 minutes) could still
  complete login and mint a session. Fixed in `app/routes/two_factor.py`.
