Status: ready-for-agent

# Release 0 — Foundation (skeleton)

## Problem Statement

TrainDrain has no substrate to build on yet: no way for a person to prove who they are, no notion of what they're allowed to do, and no way to organize people into the groups later releases will target with campaigns and content. Before any learning-content feature can exist, the platform needs identity, access, and organizational-grouping primitives that are secure by default (implicit deny, no anonymous access) and won't need to be re-architected when a fully custom permission matrix arrives in a later release.

## Solution

Ship the identity and access substrate: email+password authentication with opt-in TOTP 2FA, invite-based account creation, three fixed roles (Administrator, Content Manager, Learner) with admin-managed multi-role membership, basic User Groups, and an admin shell UI to manage all of it. Every design choice here (roles as a DB table, sessions as revocable server-side state, audit logging from day one) is made so that later releases — custom permission matrices, scoped API tokens, HRIS import — extend this foundation rather than replace it.

## User Stories

1. As an invited user, I want to set my initial password via my invite link, so that I can access the platform for the first time.
2. As a user, I want to log in with my email and password, so that I can access my account.
3. As a user, I want to log out, so that my session ends and my account stays secure on shared devices.
4. As a user who forgot my password, I want to request a password reset link via email, so that I can regain access without contacting an admin.
5. As a user resetting my password, I want the reset link to be single-use and time-limited, so that a leaked link can't be used to compromise my account later.
6. As a user, I want to be temporarily blocked from logging in if I (or an attacker) enter the wrong password too many times in a short window, so that my account isn't vulnerable to brute-force guessing.
7. As a user, I want any password I choose (at signup, reset, or change) to be rejected if it's found in a known data breach, so that I'm not using a compromised password.
8. As a user, I want my session to expire automatically after a period of inactivity or after a fixed maximum duration, so that a device I forgot to log out of doesn't stay open indefinitely.
9. As a user, I want to opt in to TOTP-based two-factor authentication, so that my account has an extra layer of security.
10. As a user setting up 2FA, I want to scan a QR code (or enter a setup key) with my authenticator app, so that I can link it to my account.
11. As a user enabling 2FA, I want to be shown a set of one-time backup recovery codes, so that I can still log in if I lose access to my authenticator app.
12. As a user logging in with 2FA enabled, I want to be prompted for a TOTP code or a recovery code after my password, so that my login is protected by both factors.
13. As a user who has lost both my authenticator device and my recovery codes, I want to be able to ask an administrator to disable 2FA on my account, so that I can regain access.
14. As an administrator, I want to disable 2FA on a user's account, so that I can help a locked-out user regain access after verifying their identity out-of-band.
15. As a user, I want to disable 2FA on my own account, so that I can turn it off if I no longer want the extra step.
16. As an administrator, I want to invite a new user by email, so that they can join the platform.
17. As an administrator, I want to optionally pre-assign roles and/or group memberships to an invite, so that the invited user has the right access as soon as they accept.
18. As an administrator, I want to choose the language (English or German) an invite is sent in, so that the invited user receives communication — and their initial account experience — in their preferred language.
19. As an administrator, I want to configure a global expiry period for invite links, so that unclaimed invites don't stay valid indefinitely.
20. As an administrator, I want to re-invite a user whose invite has expired or was never accepted, so that they can still join without a workaround.
21. As an invited user, I want my invite acceptance to auto-assign me the Learner role (in addition to anything the admin pre-assigned), so that I can log in and see assigned content immediately.
22. As an invited user, I want an expired or already-used invite link to clearly tell me it's no longer valid, so that I know to ask the admin for a new one instead of being confused.
23. As an administrator, I want to view a list of all users, so that I can manage the platform's user base.
24. As an administrator, I want to disable a user's account, so that I can immediately revoke their access without deleting their data.
25. As an administrator, I want to re-enable a previously disabled user's account, so that I can restore their access if it was disabled in error or the situation changes.
26. As an administrator, I want to permanently erase a user's personal data, so that I can comply with a right-to-erasure (GDPR) request while preserving audit-log/referential integrity.
27. As a user, I want to update my own first and last name, so that I can keep my profile accurate.
28. As a user, I want my email address to be immutable once my account exists, so that my account identity — which is also how I was invited — stays stable and unambiguous.
29. As a user, I want to set my preferred language (English or German), so that the platform's interface displays in the language I understand best.
30. As a user, I want to set my preferred theme (dark, light, or colorblind-friendly), so that the interface is comfortable and accessible for me.
31. As a user, I want my language and theme preferences to persist across devices and sessions, so that I don't have to reconfigure them every time I log in somewhere new.
32. As an administrator, I want to assign one or more roles to a user, so that I can grant them the appropriate level of access.
33. As an administrator, I want to remove a role from a user, so that I can revoke access they no longer need.
34. As an administrator, I want to view which roles exist and which users hold each one, so that I can audit who has elevated access.
35. As a user whose role membership is changed by an administrator, I want my other active sessions invalidated, so that the access change takes effect immediately rather than after my session naturally expires.
36. As an administrator, I want to create a user group, so that I can organize users by their organizational role or team.
37. As an administrator, I want to edit a group's name and description, so that I can keep group metadata accurate.
38. As an administrator, I want to delete a group, so that I can remove groups that are no longer needed.
39. As an administrator, I want to add users to a group, so that I can build the targeting units later releases will use for campaigns and module assignment.
40. As an administrator, I want to remove users from a group, so that I can keep group membership current.
41. As an administrator, I want to view a group's member list, so that I can see who currently belongs to it.
42. As an administrator, I want a dedicated admin area in the UI, so that user, group, and role management are clearly separated from learner-facing functionality.
43. As a Content Manager or Learner, I want the admin area to be entirely inaccessible to me (not just visually hidden), so that implicit deny is enforced even if I guess a URL.
44. As an administrator, I want sensitive administrative actions (invites sent, role changes, disable/enable/erase, 2FA admin-resets, group changes) recorded in an audit log, so that there's an accountability trail for compliance and troubleshooting, even before Release 0 ships a UI to browse it.
45. As a user, I want every piece of UI text to be available in both English and German, so that I can use the platform in my preferred language regardless of which screen I'm on.
46. As a user, I want the platform to default to a sensible light/dark theme based on my device settings before I've explicitly set a preference, so that it looks reasonable from my very first login.
47. As a developer running this locally, I want `docker-compose up` to give me a fully working environment (database, API, LocalStack-emulated SES, and a prod-style build of the frontend), so that I don't need bespoke local setup instructions beyond the standard command.

## Implementation Decisions

### Backend stack
- **FastAPI** (async) as the web framework; **SQLAlchemy 2.0** (async engine) as the ORM; **Alembic** for migrations. Rationale recorded in `docs/research/backend-framework-choice.md` — chosen over Django+DRF primarily because Django's built-in `Group`/permission model conflicts with this project's explicit Roles-vs-Groups domain split, plus better async/streaming fit for later AI features and native OpenAPI generation ahead of the future scoped-API-token release.
- **PostgreSQL** is the sole datastore for Release 0 — no Redis/ElastiCache. It backs: user records, sessions, roles, role membership, groups, group membership, invites, password-reset tokens, login rate-limit counters, and the audit log.

### Authentication
- Server-side sessions, referenced by an `httpOnly`, `Secure`, `SameSite=Strict` cookie. Session rows live in Postgres (not Redis, not a signed/stateless token) specifically so they can be revoked server-side.
- Session lifetime: 12-hour absolute expiry OR 30-minute idle timeout, whichever is reached first. No "remember me" option in Release 0.
- Session invalidation: changing password, enabling/disabling 2FA, or an admin changing a user's role membership invalidates that user's *other* active sessions (the session performing the action, if any, may remain alive).
- Password hashing: **Argon2id** (`argon2-cffi`).
- Password policy: 12-character minimum; no forced character-class complexity and no forced periodic rotation (NIST 800-63B posture); reject any candidate password found via the Have I Been Pwned Pwned Passwords API, queried via k-anonymity (only the first 5 hex characters of the SHA-1 hash are sent; the real password/hash never leaves our infrastructure).
- Brute-force protection: a sliding-window rate limit keyed on the `(ip, email)` pair, counters stored in a Postgres table — not a hard account lockout (a hard lockout is itself a DoS vector against a known email).
- **Forgot-password flow** (implied by "email + password authentication" scope, not separately itemized on the roadmap but necessary for the feature to be usable): a user can request a reset link for their email; a single-use, cryptographically random token (hashed at rest, like invite tokens) is emailed via the same SES/LocalStack-SES path as invites, with a short fixed expiry (1 hour — shorter than the invite expiry since this is a security-sensitive action-in-progress rather than an onboarding grace period). Using the link invalidates all of that user's other active sessions.

### Two-factor authentication
- TOTP via `pyotp`. Opt-in, per-user.
- The TOTP secret is encrypted at the application layer before being stored (envelope encryption; the encryption key is pulled from AWS Secrets Manager in production and from an environment variable locally — never hardcoded), layered on top of RDS encryption-at-rest.
- On enabling 2FA, generate ~10 single-use backup/recovery codes, displayed once, stored hashed with Argon2id (same treatment as passwords), each consumed on use.
- If a user has exhausted their recovery codes and lost their authenticator device, the only recovery path is an admin-initiated 2FA disable — no self-service email-based 2FA bypass. This action is audit-logged.

### Roles & permissions
- `roles` is a database table (`id`, `name`, `description`), seeded via migration with the three Release 0 roles — deliberately not a code-level enum, so the future custom-permission-matrix release can add `permissions` and `role_permissions` tables on top without a breaking schema change.
- Users can hold multiple roles simultaneously — a many-to-many `user_roles` join table.
- Release 0 permission scope (enforced server-side; the frontend must not be the only enforcement point):
  - **Administrator**: full read-write on everything Release 0 defines — user invite/disable/enable/erase/edit, group CRUD + membership, role assignment.
  - **Content Manager**: functionally identical to Learner in Release 0 (there is no content yet to manage). The role exists and is assignable now purely so later releases don't need new role-creation work.
  - **Learner**: read-write on their own account only (name, password, 2FA settings, language/theme preference). No visibility into other users, groups, or role data — implicit deny, enforced at the API layer, not just hidden in the UI.

### Users
- Fields: `email` (immutable — functions as the username and the invite-targeting key; not editable by the user or an admin), `first_name`, `last_name` (self-editable), `preferred_language`, `preferred_theme`.
- Two distinct removal actions, both admin-only and audit-logged:
  - **Disable/enable** (soft, reversible): kills all of the user's active sessions and blocks login; the record and its relationships (audit log entries, future grading records) are retained.
  - **Erase** (hard, GDPR right-to-erasure): anonymizes/removes personal fields (email, name); a tombstone row remains so foreign keys from the audit log and future features don't break.

### Groups
- Fields: `name`, `description`. Flat many-to-many membership (`group_members`). No nesting, no dynamic/rule-based membership (explicitly deferred past Release 0 per the roadmap).
- Admin-managed only in Release 0 — Content Manager has no group visibility yet, consistent with the permission scope above.

### Invites
- An invite is a single-use, cryptographically random token (`secrets.token_urlsafe`), stored hashed (same pattern as passwords/recovery codes/reset tokens).
- Expiry is a single global setting, configurable by Administrators, defaulting to 7 days if never configured — not a per-invite override.
- An expired or already-used invite is dead; there's no resend/extend action on the same token — the admin issues a fresh invite, which invalidates any prior pending invite to that same email.
- An admin can, at invite-creation time, pre-select additional roles and/or group memberships to apply automatically on acceptance, alongside the automatic Learner-role assignment.
- An admin picks the invite's language (English or German) at invite-creation time; this becomes the invited user's initial `preferred_language`, self-editable after they log in.
- Delivery: AWS SES in production; LocalStack's SES emulation locally (no separate mail-catcher tool, for dev/prod parity).

### Audit logging
- A basic audit log table from day one: `actor_user_id`, `action`, `target_user_id` (nullable), `timestamp`, and a small JSON detail blob.
- Logged actions: invite sent, role granted/revoked, user disabled/enabled/erased, 2FA admin-reset, group created/deleted, group membership changed.
- No dedicated browsing UI in Release 0 — the goal is to ensure the data exists to be queried later, since it cannot be retrofitted onto actions that already happened.

### Frontend
- **React + Vite** SPA (not Next.js — the entire app sits behind a login wall, so there's no SSR/SEO benefit), **React Router** for client-side routing. Communicates with the FastAPI backend purely over its API, per the project-wide requirement that the API be independently usable.
- **Tailwind CSS + shadcn/ui** (Radix-based, components copied into the repo rather than an opaque npm dependency) **+ Motion** for animation/microinteractions. Rationale recorded in `docs/research/frontend-ui-library-choice.md` — chosen over MUI/Chakra/Mantine primarily for CSS-variable theming that extends cleanly to a third (colorblind-friendly) theme, and Radix's accessibility-first primitives fitting a compliance/training platform.
- **react-i18next** for English/German; every UI string is routed through `t()`.
- Theme preference (dark/light/colorblind-friendly) and language preference are both stored server-side on the user's profile (not `localStorage`), so they follow the user across devices. A brand-new user with no stored preference gets a `prefers-color-scheme`-based default (light or dark only — the colorblind theme is always an explicit opt-in, never a default).

### Infrastructure (AWS eu-central-1)
- Backend: **ECS Fargate** behind an ALB — chosen over Lambda because LocalStack's own documentation states Lambda response streaming isn't supported (a blocker for locally testing the future streaming AI chat feature), and because Fargate fits the long-running, Postgres-backed session/rate-limit model better than Lambda's stateless-per-invocation model.
- Frontend: static build served via **S3 + CloudFront**, deployed independently from the backend, on a sibling subdomain of the API so the `SameSite=Strict` session cookie remains workable.
- Terraform under `.deploy/dev` for this release, following the AWS Terraform best-practice references already listed in AGENTS.md.
- Local dev: `docker-compose` runs Postgres, the FastAPI backend, and LocalStack (SES emulation). The Vite dev server runs natively on the host for hot module reload during day-to-day frontend work; a prod-style static-build frontend service is also included in `docker-compose` so `docker-compose up` alone still produces a fully working environment.

## Testing Decisions

- **Primary seam — backend API, against a real database.** Backend tests exercise the FastAPI application through its HTTP interface (`httpx.AsyncClient` or FastAPI's `TestClient`) against a real, ephemeral Postgres test database — not a mocked ORM or mocked DB layer. This is the highest available seam (the actual contract other consumers rely on) and catches real query/constraint bugs that a mocked-DB test would hide. Use `pytest` + `pytest-asyncio` as the test runner.
- **Frontend seam — rendered components, from the user's perspective.** Frontend tests use **Vitest + React Testing Library**, asserting on rendered output and user-observable behavior (what's on screen, what happens on click/submit) rather than internal component state or implementation details. Network calls to the backend are the natural mock boundary here (e.g. via MSW or a lightweight fetch mock) — the frontend seam does not also stand up a real backend.
- This is a greenfield project — there is no prior test suite to follow as precedent. These two seams (API-level backend tests, component-level frontend tests) establish the pattern subsequent releases should reuse rather than introducing new seams per feature.
- Specific areas needing test coverage: password/2FA/session lifecycle (including rate-limiting and session invalidation on sensitive changes), invite issuance/acceptance/expiry, role and group CRUD plus their permission enforcement (explicitly test that a Learner is denied admin-shell endpoints, not just that an Administrator is allowed), and the disable/enable/erase user flows.

## Out of Scope

- Anything content-related: Learning Modules, Campaigns, quizzes/grading, AI chat or AI-assisted authoring, dashboards, RSS/news nuggets (Releases 1–6).
- A fully custom, admin-authored permission matrix (arbitrary roles, per-action read/write/none editing) — Release 0 ships only the three fixed roles.
- Scoped API tokens for independent API access — deferred until real resource types exist to scope against.
- HRIS / Google Workspace bulk user import (Release 8) — Release 0 is invite-only.
- Nested or dynamic/rule-based group membership.
- Per-deployment branding/theming (custom colors/logo/motifs) beyond the three baseline themes (dark, light, colorblind-friendly) — that's Release 7.
- An admin-facing UI to browse the audit log (the data is captured; the viewer is not built yet).
- Redis/ElastiCache for sessions or rate-limiting — deferred until Postgres-backed state becomes an actual bottleneck.
- An admin-level "enforce 2FA for all users" toggle — Release 0 ships only per-user opt-in 2FA.
- "Remember me" / long-lived sessions.

## Further Notes

- Two research documents back the two most consequential technology choices in this spec and should be read alongside it: `docs/research/backend-framework-choice.md` (FastAPI vs. Django+DRF) and `docs/research/frontend-ui-library-choice.md` (Tailwind+shadcn/ui vs. MUI/Chakra/Mantine).
- This project has no `gh` CLI available and no issue tracker configured yet (no `docs/agents/issue-tracker.md`); this PRD is filed under the local-markdown convention (`.scratch/<feature>/PRD.md`) as an interim measure. Running `/setup-matt-pocock-skills` to formally configure a tracker is recommended before the next release's spec, if the project moves to GitHub Issues later.
- The forgot-password flow was added under Implementation Decisions even though it wasn't a separately itemized roadmap bullet — email+password authentication is not usable in practice without a way to recover from a forgotten password, and its design (single-use hashed token, SES delivery) directly reuses patterns already agreed for invites, so it introduces no new architectural surface.
