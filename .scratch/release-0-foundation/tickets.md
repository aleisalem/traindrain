# Tickets: Release 0 — Foundation (skeleton)

Identity, access, and organizational-grouping substrate for TrainDrain: email+password auth with opt-in TOTP 2FA, invite-based account creation, three fixed roles, basic User Groups, and an admin shell UI. Source spec: `.scratch/release-0-foundation/PRD.md`.

Work the **frontier**: any ticket whose blockers are all done.

## 1. Project scaffold: local dev environment + i18n/theme infrastructure

**What to build:** A developer can run `docker-compose up` and get a fully working environment: Postgres, a FastAPI backend with a health-check endpoint, LocalStack running SES emulation, and a prod-style static build of the frontend, alongside a Vite dev server for hot-module-reload during day-to-day frontend work. Alembic migrations are wired up (even if the first migration is empty/near-empty). The frontend has react-i18next configured for English/German and a Tailwind CSS-variable theme system with all three themes (dark, light, colorblind-friendly) defined, so every later screen just consumes `t()` and theme tokens instead of re-deriving the setup.

**Blocked by:** None — can start immediately.

- [x] `docker-compose up` starts Postgres, FastAPI, LocalStack (SES), and a prod-style frontend build with no bespoke setup steps
- [x] Vite dev server runs natively on the host for frontend HMR, per project convention
- [x] Backend has a health endpoint and Alembic is wired to the Postgres service
- [x] react-i18next is configured with EN and DE locale files (even if mostly placeholder strings) and a working `t()` call renders on a placeholder page
- [x] Tailwind CSS variables define dark, light, and colorblind-friendly themes; a placeholder page can switch between them
- [x] README updated with local run instructions per AGENTS.md documentation requirements

## 2. Core identity schema: users, roles, sessions, audit log, bootstrap admin

**What to build:** The foundational data model everything else builds on, plus a bootstrap Administrator account so there's someone able to log in and issue the first invite. On first seed, a cryptographically random password is generated for the bootstrap admin, hashed with Argon2id before storage, and the plaintext is written to the application logs (never persisted in plaintext, never emailed — SES infra doesn't exist yet at this point). The account is flagged to require a password change before it can be used for anything else. The shared password-policy validator (12-char minimum, HIBP k-anonymity breach check) is built here as an independently-testable utility, since both the forced first-login change (ticket 3) and invite-acceptance (ticket 5) need it. The audit log table and a small logging helper are also introduced here as shared infrastructure for every ticket that performs a sensitive action.

**Blocked by:** 1

- [x] Migrations create `users`, `roles` (seeded with Administrator, Content Manager, Learner), `user_roles`, `sessions`, and `audit_log` tables
- [x] Bootstrap Administrator is seeded with a cryptographically random password (not env-configured), hashed with Argon2id, `must_change_password` flag set to true
- [x] The random password is written to application logs on seed and nowhere else in plaintext
- [x] Shared password-policy validator: rejects passwords under 12 characters and any password found via the HIBP Pwned Passwords API (k-anonymity, only first 5 SHA-1 hex chars sent) — unit-testable without any endpoint
- [x] `audit_log` helper function is callable and writes `actor_user_id`, `action`, `target_user_id`, `timestamp`, and a JSON detail blob
- [x] Tests verify: 3 roles seeded, bootstrap admin exists with a hashed (non-plaintext) password and `must_change_password = true`, password validator accepts/rejects correctly

## 3. Login, logout, session lifecycle, forced first-login password change, rate limiting

**What to build:** A user (starting with the bootstrap admin) can log in with email + password and log out. Sessions are server-side rows referenced by an httpOnly/Secure/SameSite=Strict cookie, expiring after 12 hours absolute or 30 minutes idle, whichever comes first. Repeated failed logins for an (ip, email) pair are rate-limited via a sliding window, not a hard lockout. If the authenticated user has `must_change_password` set (true for the bootstrap admin on first login), every action except setting a new password is blocked until they do so, reusing the validator from ticket 2.

**Blocked by:** 2

- [x] POST login endpoint: validates credentials, creates a server-side session row, sets httpOnly/Secure/SameSite=Strict cookie
- [x] POST logout endpoint: revokes the current session
- [x] Session expires at 12h absolute or 30min idle, whichever is first; expired session is rejected on next request
- [x] Sliding-window rate limit on (ip, email) pair, backed by a Postgres table; blocks further attempts temporarily without permanently locking the account
- [x] Bootstrap admin can log in with the logged random password; all endpoints other than "change my password" return a blocked/forced-change response until they set a new password
- [x] Setting the new password clears `must_change_password`, re-validates via the ticket 2 policy validator, and is Argon2id-hashed
- [x] Minimal login UI screen (uses i18n/theme infra from ticket 1)
- [x] Tests: login success/failure, logout, idle/absolute expiry, rate-limit triggering, forced-change gate blocking/unblocking access

## 4. Admin shell UI & implicit-deny route guarding

**What to build:** A dedicated admin area in the UI, structurally separate from learner-facing screens, with its own navigation. A stub admin-only endpoint proves implicit deny end to end: a Learner or Content Manager gets a 403 (not just a hidden nav item) if they hit the endpoint directly, and doesn't see the admin nav entry at all. An Administrator sees the admin shell and can reach the stub endpoint.

**Blocked by:** 3

- [x] Admin area exists as a separate route tree in the frontend, with nav only visible to Administrators
- [x] A stub admin-only backend endpoint enforces the Administrator role server-side (not just hidden client-side)
- [x] Test: Learner and Content Manager sessions get 403 on the stub endpoint even when navigating directly by URL
- [x] Test: Administrator session succeeds

## 5. Admin invites a user; invite acceptance sets password

**What to build:** An Administrator can invite a new user by email, optionally pre-assigning roles, in a chosen language (EN/DE). The invite is a single-use, cryptographically random token, hashed at rest, delivered via SES (LocalStack locally). A global expiry period (admin-configurable, default 7 days) governs validity. An expired or used invite clearly tells the visitor it's no longer valid rather than erroring opaquely. An admin can re-invite, which invalidates any prior pending invite to that email. Accepting an invite lets the invited user set their initial password (via the ticket 2 validator) and creates their account, auto-assigning the Learner role plus anything the admin pre-assigned.

**Blocked by:** 3, 4

- [x] Admin-only endpoint + admin shell page: create invite (email, optional role pre-assignment, language)
- [x] Invite token is single-use, cryptographically random (`secrets.token_urlsafe`), stored hashed
- [x] Global invite-expiry setting is admin-configurable, defaults to 7 days
- [x] Invite email is sent via SES/LocalStack-SES in the invite's chosen language
- [x] Accept-invite flow: sets password (reusing ticket 2 validator), creates the user, auto-assigns Learner + pre-assigned roles
- [x] Expired or already-used invite shows a clear "no longer valid" message, not a generic error
- [x] Re-inviting the same email invalidates the prior pending invite and issues a fresh token
- [x] All invite issuance is audit-logged
- [x] Tests: issue, accept, expiry, reuse-rejection, re-invite invalidation, role pre-assignment on acceptance

## 6. Forgot-password flow

**What to build:** A user who forgot their password can request a reset link by email. The link uses a single-use, hashed, cryptographically random token with a 1-hour expiry, delivered via the same SES path invites use. Using the link invalidates all of that user's other active sessions and requires the new password to pass the ticket 2 policy validator.

**Blocked by:** 3, 5

- [x] Request-reset endpoint: accepts an email, issues a hashed single-use token with 1h expiry, sends via SES/LocalStack-SES (no account-existence leak in the response)
- [x] Reset endpoint: validates token, enforces the ticket 2 password validator, sets the new password
- [x] Using the link invalidates the user's other active sessions
- [x] Tests: request, successful reset, expired token, reused token, session invalidation on reset

## 7. TOTP 2FA enrollment & login with 2FA

**What to build:** A logged-in user can opt in to TOTP-based 2FA: scan a QR code or enter a setup key, see ~10 one-time backup/recovery codes exactly once, and from then on is prompted for a TOTP or recovery code after their password at login. The TOTP secret is encrypted at the application layer before storage; recovery codes are hashed with Argon2id and consumed on use.

**Blocked by:** 3

- [x] Enrollment endpoint: generates a TOTP secret (encrypted at rest via envelope encryption, key from env var locally), returns a QR code / setup key
- [x] On enable, ~10 backup codes are generated, shown once, stored hashed, single-use
- [x] Login flow: if 2FA is enabled, password success leads to a second step requiring a valid TOTP or recovery code before a session is issued
- [x] Tests: enroll, login with valid TOTP, login with valid recovery code (code becomes unusable after), login rejected with bad code

## 8. 2FA recovery: self-disable and admin-disable

**What to build:** A user can disable 2FA on their own account. A user who has lost both their authenticator and their recovery codes can ask an Administrator to disable 2FA on their behalf after out-of-band identity verification; the admin action is available from the admin shell and is audit-logged.

**Blocked by:** 7, 4

- [x] Self-service endpoint: authenticated user disables their own 2FA
- [x] Admin-only endpoint + admin shell UI: disable 2FA on a target user's account
- [x] Admin 2FA-disable action is audit-logged
- [x] Tests: self-disable, admin-disable, non-admin forbidden from disabling another user's 2FA

## 9. Admin user management: list, disable, enable, erase

**What to build:** An Administrator can view all users, disable an account (kills active sessions, blocks login, retains data/relationships), re-enable a disabled account, and permanently erase a user's personal data for GDPR right-to-erasure (anonymizing personal fields while leaving a tombstone row so audit-log and future foreign keys don't break). All of these are audit-logged.

**Blocked by:** 5, 4

- [x] Admin shell page + endpoint: list all users
- [x] Disable endpoint: revokes active sessions, blocks future login, retains the record
- [x] Enable endpoint: restores login ability
- [x] Erase endpoint: anonymizes/removes personal fields, leaves a tombstone row that audit-log foreign keys still resolve against
- [x] All four actions are audit-logged
- [x] Tests: list, disable blocks login + kills sessions, enable restores, erase anonymizes but preserves referential integrity

## 10. Role assignment management + session invalidation on role change

**What to build:** An Administrator can assign one or more roles to a user, remove a role from a user, and view which roles exist and who holds each. Changing a user's role membership invalidates that user's other active sessions so the access change takes effect immediately.

**Blocked by:** 5, 4

- [x] Admin shell page + endpoints: assign role to user, remove role from user, view roles with their members
- [x] Changing a user's roles invalidates their other active sessions (not the session performing the action, if it's their own)
- [x] Action is audit-logged
- [x] Tests: assign, remove, view, session invalidation on change, non-admin forbidden

## 11. Groups: CRUD, membership, invite group pre-assignment

**What to build:** An Administrator can create, edit, and delete User Groups (name + description), add and remove users from a group, and view a group's member list. Invite creation (ticket 5) is extended so an admin can also pre-select group memberships at invite time, applied on acceptance alongside role pre-assignment.

**Blocked by:** 5, 4

- [x] Admin shell pages + endpoints: group CRUD, add/remove member, view members
- [x] Invite-creation endpoint/UI extended with optional group pre-assignment, applied on invite acceptance
- [x] Group CRUD and membership changes are audit-logged
- [x] Tests: CRUD, membership add/remove, member listing, invite-time group pre-assignment on acceptance, non-admin forbidden

## 12. User profile self-service: name, password change, language/theme preference

**What to build:** A logged-in user can update their own first/last name, change their own password (reusing the ticket 2 policy validator; changing it invalidates their other active sessions), and set their preferred language (EN/DE) and theme (dark/light/colorblind-friendly), both persisted server-side so they follow the user across devices. A brand-new user with no stored preference gets a `prefers-color-scheme`-based default (light or dark only — colorblind is always an explicit opt-in). Email remains immutable and is not editable through this endpoint.

**Blocked by:** 3

- [ ] Self-service endpoint: update first/last name
- [ ] Self-service endpoint: change own password (ticket 2 validator, invalidates other active sessions)
- [ ] Self-service endpoint: set preferred language and theme, persisted server-side on the user record
- [ ] Attempting to edit email is rejected
- [ ] New user with no stored theme preference gets an OS-based light/dark default, never colorblind by default
- [ ] Profile UI screen uses i18n/theme infra from ticket 1
- [ ] Tests: name update, password change + session invalidation, language/theme persistence across a new session, email-edit rejection, default-theme behavior for a fresh user
