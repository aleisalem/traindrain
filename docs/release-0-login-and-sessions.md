# Release 0 — Login, sessions, forced password change, rate limiting

Implements ticket 3 of Release 0 (`.scratch/release-0-foundation/tickets.md`).

## What changed

- Added `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me`, and
  `POST /api/auth/change-password` (`src/backend/app/routes/auth.py`).
- `src/backend/app/security/sessions.py`: server-side session lifecycle — `create_session`,
  `get_valid_session` (enforces 12h absolute / 30min idle expiry, refreshing the idle clock on
  every valid use), `revoke_session`, `revoke_other_sessions`, and the httpOnly/Secure/
  SameSite=Strict cookie helpers. Session tokens are opaque (`app.security.tokens`,
  `secrets.token_urlsafe`) and stored as a SHA-256 hash, not Argon2id — unlike passwords they're
  already high-entropy and looked up by exact match, so a fast deterministic hash is the right
  tool (Argon2id's salt would make a direct `WHERE token_hash = ...` lookup impossible).
- `src/backend/app/security/rate_limit.py`: sliding-window brute-force protection on the
  `(email, ip)` pair, backed by a new `login_attempts` table (one row per *failed* attempt; the
  window is computed by counting rows at check time, so old attempts age out on their own rather
  than needing a reset). Defaults to 10 attempts / 15 minutes. A rate-limited request is rejected
  with 429 before the password is even checked.
- `src/backend/app/dependencies.py`: `get_current_user` (valid session only) backs `/logout` and
  `/change-password` — a user who still has `must_change_password` set can log out or set a new
  password. `require_active_user` layers a 403 (`{"code": "password_change_required"}`) on top for
  every other endpoint, **including `/me`** — a forced-change session gets a 403 there too, not a
  200 with `must_change_password: true`, so "all endpoints other than change-password are blocked"
  actually holds for the one other endpoint this ticket ships, not just in a standalone unit test
  (`tests/test_dependencies.py` covers the dependency directly; `tests/test_auth_routes.py`'s
  `test_forced_password_change_flow` proves it over real HTTP). The frontend's `useAuth` hook reads
  that 403 to know to show the forced-change screen, rather than needing a special-cased "check my
  own status" endpoint exempt from the gate.
- Login always returns the same generic "Invalid email or password" message whether the email is
  unknown or the password is wrong, so the endpoint can't be used to enumerate accounts by
  response content. It also can't be used to enumerate by *timing*: an unknown email still runs a
  full Argon2id verify against a fixed dummy hash (`_DUMMY_PASSWORD_HASH` in
  `app/routes/auth.py`), so that path costs the same as a wrong-password one.
- Rate-limiting reads the client IP from the first `X-Forwarded-For` entry when present, falling
  back to the raw peer address — the app is always reached through exactly one reverse-proxy hop
  (nginx locally, the ALB in AWS per the PRD), so `request.client.host` alone would just be that
  proxy's address for every user, collapsing the whole `(email, ip)` sliding window onto one IP.
- Changing your password (forced or not) invalidates your other active sessions, per the PRD's
  cross-cutting session-invalidation rule — the session used to make the change stays alive.
- Frontend: `src/frontend/src/features/auth/` (`useAuth` hook, `LoginForm`,
  `ForcedPasswordChangeForm`) plus `src/frontend/src/Dashboard.tsx` (the old scaffold placeholder,
  now gated behind a session and carrying a logout button). `App.tsx` is now a thin state machine
  over `useAuth`'s status (`loading` / `anonymous` / `forced_password_change` / `authenticated`).
  All new strings are routed through `t()` with EN/DE translations.

## Notes

- Session/rate-limit thresholds (12h/30min, 10 attempts per 15 minutes) are fixed constants, not
  `Settings` fields — the PRD calls them out as fixed behavior, unlike invite expiry (ticket 5),
  which is explicitly admin-configurable.
- No admin-shell UI or role checks yet (ticket 4) — today, every authenticated user (once past
  the forced-change gate) has access to the same placeholder dashboard.
- `email-validator` was added as a new runtime dependency (`pydantic.EmailStr` needs it).
- Login, logout, and self password-change are deliberately **not** written to `audit_log`. The
  PRD's Audit logging section enumerates the actions that are: "invite sent, role granted/revoked,
  user disabled/enabled/erased, 2FA admin-reset, group created/deleted, group membership changed"
  — all admin-on-another-user actions. Ordinary login/logout/self-password-change aren't on that
  list.
