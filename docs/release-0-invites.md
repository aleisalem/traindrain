# Release 0 — Admin invites a user; invite acceptance sets password

Implements ticket 5 of Release 0 (`.scratch/release-0-foundation/tickets.md`).

## What changed

- New tables: `invites` (single-use, hashed token — same pattern as sessions —
  plus `email`, `language`, `invited_by_user_id`, `expires_at`, `accepted_at`,
  `revoked_at`), `invite_roles` (many-to-many pre-assigned roles), and a small
  `system_settings` key/value table seeded with `invite_expiry_days = 7`.
- `POST /api/admin/invites` (`require_administrator`): creates an invite for
  an email not already tied to an account, optionally pre-assigning roles and
  a language, invalidates any prior pending invite to the same email (a
  re-invite), and sends the invite email — only committing once the send
  succeeds, so a failed send leaves no half-issued invite behind. Logged to
  `audit_log` as `invite_sent`.
- `GET /api/admin/roles` and `GET`/`PUT /api/admin/settings/invite-expiry-days`
  (both admin-only) back the invite-creation UI's role picker and the
  admin-configurable global expiry.
- `GET /api/invites/{token}` and `POST /api/invites/{token}/accept` are the
  only unauthenticated endpoints in the app besides login itself — an invited
  user isn't a session yet. Both treat "never existed", "expired", "already
  accepted", and "revoked by a re-invite" identically (410, generic "no
  longer valid" message) rather than leaking which reason applies. Accepting
  reuses the ticket 2 password-policy validator, creates the user with
  Learner plus any pre-assigned roles, and does not auto-log-in — the user is
  sent to the normal login screen afterward.
- `app/security/mailer.py` + `app/dependencies.get_ses_client`: a thin,
  dependency-injected wrapper around boto3's SES client (offloaded to a
  thread since boto3 is synchronous), sending a plain-text EN/DE invite email
  built from the invite's chosen language. Tests override `get_ses_client`
  with an in-memory fake (`tests/conftest.py`) so they never touch
  LocalStack.
- `app/main.py` gained a startup hook that verifies the SES sender identity
  against LocalStack when `AWS_ENDPOINT_URL` is set — LocalStack's SES
  emulation rejects sends from an unverified sender, unlike production SES
  where verification happens out-of-band (domain/DKIM), so this only runs
  locally.
- `docker-compose.yml`: the backend service gained `AWS_REGION`,
  `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` (LocalStack accepts any value —
  not real secrets, and unused in production, where boto3 uses the ECS task
  role instead), `SES_SENDER_EMAIL`, and `FRONTEND_BASE_URL` (used to build
  the link in the invite email).
- Frontend: `features/admin/InviteUserPage.tsx` (email, language, role
  checkboxes; reachable at `/admin/invites` via a new "Invite user" nav link
  in the admin shell) and `features/invites/AcceptInvitePage.tsx` (checks the
  invite, then collects and confirms a new password). `/accept-invite` is
  the only frontend route reachable regardless of session state, since a
  visitor following the link isn't signed in yet. All new strings are
  routed through `t()` with EN/DE translations.

## Notes

- Verified against the real local stack (not just the test fakes): rebuilt
  the backend image, logged in, created an invite, and confirmed LocalStack's
  SES emulation (`GET /_aws/ses`) actually received it with the right
  subject/body/link, then walked the returned token through
  `GET`/`POST /api/invites/{token}` end to end.
- Two bugs only the real container caught, not the unit tests: `email-validator`
  (needed for Pydantic's `EmailStr`) was present in the local dev venv from
  some earlier, undeclared install, so it wasn't in `pyproject.toml` and the
  Docker build failed — fixed by depending on `pydantic[email]`. And
  LocalStack's SES emulation actually enforces sender-identity verification
  (contrary to the assumption in the ticket that it wouldn't need any
  special setup) — fixed with the startup verification hook above.
- Groups don't exist yet (ticket 11), so invite-time group pre-assignment
  isn't part of this ticket — only role pre-assignment. The invite schema
  and acceptance flow are written so ticket 11 can add group pre-assignment
  alongside roles without changing the shape of what's already here.
- No endpoint to list issued invites — the ticket only calls for creating and
  accepting them; an admin-facing invite list can follow later if it turns
  out to be needed.
