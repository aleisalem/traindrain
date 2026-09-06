# TrainDrain

A customizable e-learning and security-awareness platform. See [AGENTS.md](AGENTS.md) for the
full product vision and [docs/ROADMAP.md](docs/ROADMAP.md) for how it's being built out release
by release.

## Currently supported

Release 0 is in progress. So far:

- Local dev environment: Postgres, a FastAPI backend, LocalStack (SES emulation), and a
  prod-style static frontend build, all runnable via `docker-compose up`.
- Backend health-check endpoint (`GET /api/health`) with Alembic migrations wired to Postgres.
- Frontend i18n (English/German via react-i18next) and a Tailwind CSS-variable theme system
  (light, dark, colorblind-friendly).
- Core identity schema: `users`, `roles` (seeded with Administrator, Content Manager, Learner),
  `user_roles`, `sessions`, and `audit_log` tables, plus a bootstrap Administrator account seeded
  on first migration (its one-time random password is written to the backend's logs). Shared
  Argon2id password hashing and a password-policy validator (12-char minimum, HIBP breach check)
  live in `app.security` for reuse by the login/invite features that consume them next.
- Email+password login and logout, backed by server-side sessions (httpOnly/Secure/
  SameSite=Strict cookie; 12h absolute / 30min idle expiry) — `POST /api/auth/login`,
  `POST /api/auth/logout`, `GET /api/auth/me`. Repeated failed logins for an (email, ip) pair are
  sliding-window rate-limited. A user with `must_change_password` set (the bootstrap admin, on
  first login) gets a 403 from every endpoint but `/api/auth/logout` and
  `POST /api/auth/change-password` until they set a new password; changing your password
  invalidates your other active sessions. A minimal login / forced-password-change UI lives in
  `src/frontend/src/features/auth/`.
- An admin area (`/admin`), structurally separate from the learner-facing dashboard, with its own
  navigation — visible only to users holding the Administrator role. A stub admin-only endpoint
  (`GET /api/admin/ping`) enforces that role server-side (`require_administrator` in
  `app/dependencies.py`), so a Learner or Content Manager gets a 403 even navigating there
  directly, not just a hidden nav item. Frontend routing uses React Router
  (`src/frontend/src/App.tsx`, `src/frontend/src/features/admin/`).
- Admin-issued invites (`POST /api/admin/invites`, admin shell page at `/admin/invites`):
  single-use, hashed tokens emailed via SES/LocalStack-SES in the admin's chosen language, with
  optional role pre-assignment and an admin-configurable global expiry (`GET`/`PUT
  /api/admin/settings/invite-expiry-days`, default 7 days). Re-inviting an email invalidates its
  prior pending invite. `GET`/`POST /api/invites/{token}` (public — the invited user isn't a
  session yet) let a visitor check an invite and set their initial password, auto-assigning the
  Learner role plus anything the admin pre-assigned; an expired/used/superseded invite shows a
  clear "no longer valid" message. All invite issuance is audit-logged. Frontend:
  `src/frontend/src/features/admin/InviteUserPage.tsx` and
  `src/frontend/src/features/invites/AcceptInvitePage.tsx`.
- Forgot-password flow: `POST /api/auth/forgot-password` (email in, always 204 out — the
  response never leaks whether an account exists) emails a single-use, hashed, 1-hour-expiry
  reset token via SES/LocalStack-SES; a fresh request supersedes any still-pending one.
  `POST /api/auth/reset-password` validates the token, enforces the same password-policy
  validator, sets the new password, and invalidates all of that user's other active sessions.
  Frontend: `src/frontend/src/features/auth/ForgotPasswordPage.tsx` and
  `ResetPasswordPage.tsx`, reachable at `/forgot-password` and `/reset-password` without a
  session, plus a "Forgot your password?" link on the login form.
- Opt-in TOTP two-factor authentication: `POST /api/auth/2fa/enroll` generates a TOTP secret
  (envelope-encrypted with AES-256-GCM before storage, key from `TWO_FACTOR_ENCRYPTION_KEY`) and
  returns a QR code plus setup key; `POST /api/auth/2fa/enable` confirms it with a real TOTP code
  and returns ~10 Argon2id-hashed, single-use recovery codes shown once. Once enabled, a
  password-only `POST /api/auth/login` no longer issues a session — it sets a short-lived (5min),
  httpOnly `2FA challenge` cookie and returns `two_factor_required: true`; the real session is
  only issued by `POST /api/auth/2fa/verify` after a valid TOTP or recovery code (rate-limited the
  same way login is). `GET /api/auth/me` reports `two_factor_enabled`. A user can disable their
  own 2FA (`POST /api/auth/2fa/disable`, confirmed with their current password), and an
  Administrator can disable 2FA on a locked-out user's behalf after out-of-band identity
  verification (`POST /api/admin/users/2fa/disable`, audit-logged as `two_factor_admin_disabled`).
  Frontend: `src/frontend/src/features/auth/TwoFactorVerifyForm.tsx` (login-time second step),
  `src/frontend/src/features/twoFactor/TwoFactorSettings.tsx` (self-service enroll/disable flow on
  the dashboard), and `src/frontend/src/features/admin/AdminDisableTwoFactorPage.tsx`
  (`/admin/two-factor`, admin recovery UI).
- Admin user management: `GET /api/admin/users` lists every user with their roles and
  disabled/erased status. `POST /api/admin/users/{id}/disable` blocks an account's login and
  revokes its active sessions without deleting anything (reversible via
  `POST /api/admin/users/{id}/enable`); `POST /api/admin/users/{id}/erase` is the permanent,
  GDPR right-to-erasure action — it anonymizes the account's email and name (replacing the
  password with an unusable one and revoking sessions) while keeping a tombstone row so the audit
  log's foreign keys keep resolving. All three mutating actions are audit-logged; an admin can't
  disable or erase their own account. Frontend: `src/frontend/src/features/admin/AdminUsersPage.tsx`
  (`/admin/users`).
- Role assignment: `GET /api/admin/roles/{role_id}/members` lists who holds a role.
  `POST`/`DELETE /api/admin/users/{id}/roles/{role_id}` assign or remove a role from a user (404
  unknown user/role, 409 already-held/not-held; assigning to an erased account is also a
  conflict, removal isn't). Changing a user's roles revokes their other active sessions
  immediately — except when an admin changes their own roles, where the session performing the
  action is kept alive. All three actions are audit-logged. Frontend:
  `src/frontend/src/features/admin/AdminRolesPage.tsx` (`/admin/roles`), one card per role listing
  its members with assign/remove controls.
- User Groups: `GET`/`POST /api/admin/groups` list/create a group (name + description, 409 on a
  duplicate name); `PUT`/`DELETE /api/admin/groups/{id}` rename/redescribe or delete one (deleting
  cascades its membership rows). `GET /api/admin/groups/{id}/members` lists members;
  `POST`/`DELETE /api/admin/groups/{id}/members/{user_id}` add/remove one (404 unknown group/user,
  409 already-member/not-a-member; adding an erased user is also a conflict, removal isn't).
  Unlike roles, group membership changes don't revoke sessions — groups are for targeting future
  learning campaigns, not access control. Invite creation (`POST /api/admin/invites`) also accepts
  `group_ids` to pre-assign group membership, applied on acceptance alongside pre-assigned roles.
  All group CRUD and membership actions are audit-logged. Frontend:
  `src/frontend/src/features/admin/AdminGroupsPage.tsx` (`/admin/groups`).

Learning-content features don't exist yet — those land starting with Release 1.

## Project structure

```
src/
  backend/         FastAPI app (Python, SQLAlchemy 2.0 async, Alembic)
    app/           Application code
      models/      SQLAlchemy models
      routes/      API endpoints (FastAPI routers)
      schemas/     Pydantic request/response models
      security/    Passwords, sessions, tokens, rate limiting, audit logging
      dependencies.py   Shared FastAPI dependencies (auth/session gates)
    alembic/       Database migrations
    tests/         pytest suite, run against a real Postgres instance
  frontend/        React + Vite SPA (TypeScript)
    src/
      features/auth/   Login / forced-password-change / forgot-, reset-password, and 2FA-verify UI, auth state hook
      features/admin/  Admin-only route tree (shell nav, overview, invite-a-user page, 2FA admin-disable page, user management page, role assignment page, groups page)
      features/invites/  Public accept-invite page (set password, no session required)
      features/twoFactor/  Self-service TOTP enroll/disable UI (QR code, recovery codes)
      i18n/        react-i18next config and en/de locale files
      styles/      Tailwind CSS-variable theme definitions (light/dark/colorblind)
      theme/       Theme-selection hook
docs/              Feature summaries and research notes
.scratch/          Working specs/tickets for the release currently in progress
```

## Running locally

Prerequisites: Docker and Docker Compose.

```bash
cp .env.example .env   # required — docker-compose needs POSTGRES_PASSWORD set
# Generate your own TWO_FACTOR_ENCRYPTION_KEY in .env (needed for 2FA to work):
python3 -c "import secrets, base64; print(base64.b64encode(secrets.token_bytes(32)).decode())"
docker-compose up
```

This starts:

- Postgres on `localhost:5433` (mapped off the default 5432 to avoid clashing with a host-installed
  Postgres; override with `POSTGRES_HOST_PORT` in `.env`)
- LocalStack (SES emulation) on `localhost:4566`
- The backend API on `localhost:8000` (runs Alembic migrations on startup, which seeds a
  bootstrap Administrator account — find its one-time password with
  `docker-compose logs backend | grep traindrain.bootstrap`)
- A prod-style static build of the frontend, served via nginx, on `localhost:8080`

For day-to-day frontend development with hot-module-reload, run the Vite dev server natively on
the host instead of relying on the containerized build:

```bash
cd src/frontend
npm install
npm run dev
```

The Vite dev server proxies `/api` requests to the backend at `localhost:8000`, so keep the
backend (and Postgres) running via `docker-compose up` (or `docker-compose up postgres backend
localstack`) while you work on the frontend.

## Running tests

Backend (requires a reachable Postgres — `docker-compose up postgres` is enough):

```bash
cd src/backend
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest   # defaults to postgresql+asyncpg://traindrain:traindrain@localhost:5433/traindrain;
         # override with DATABASE_URL if your Postgres differs. Also needs
         # TWO_FACTOR_ENCRYPTION_KEY set (any base64-encoded 32 bytes) — the
         # conftest.py fixtures default one in for local runs.
```

Tests run against a real Postgres database — the fixtures in `tests/conftest.py` apply Alembic
migrations once per test session and wrap each test in a transaction that's rolled back
afterwards, so tests can freely write data without polluting `docker-compose`'s dev database.

Frontend:

```bash
cd src/frontend
npm install
npm run test        # Vitest + React Testing Library
npx tsc -b           # typecheck
```

## Deploying to AWS

Not yet set up. Terraform under `.deploy/<environment>` and the ECS Fargate / S3+CloudFront
infrastructure described in the Release 0 spec (`.scratch/release-0-foundation/PRD.md`) land in a
later ticket.
