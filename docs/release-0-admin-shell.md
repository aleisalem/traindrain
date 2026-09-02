# Release 0 — Admin shell UI & implicit-deny route guarding

Implements ticket 4 of Release 0 (`.scratch/release-0-foundation/tickets.md`).

## What changed

- `src/backend/app/dependencies.py`: `require_administrator` layers on top of
  `require_active_user` and 403s unless `"Administrator"` is one of the current user's role
  names. Enforced server-side regardless of what the frontend shows or hides.
- `src/backend/app/routes/admin.py`: `GET /api/admin/ping`, gated by `require_administrator` —
  a stub endpoint whose only purpose is to prove the gate works end to end before any real
  admin functionality (invites, user/role/group management) lands in later tickets.
- Frontend: added `react-router-dom` (per the PRD's frontend stack) and gave the authenticated
  app an actual route tree (`src/frontend/src/App.tsx`) instead of always rendering the
  dashboard directly. `/admin` and its children (`src/frontend/src/features/admin/AdminShell.tsx`,
  `AdminOverview.tsx`) are a structurally separate area with its own nav (a "back to dashboard"
  link and its own logout button), distinct from the learner-facing `Dashboard`.
- The `/admin` route is only ever registered in the route tree when the signed-in user holds the
  Administrator role (`AuthenticatedRoutes` in `App.tsx`) — a Learner or Content Manager has no
  route to fall into at all, so a direct URL visit falls through to the wildcard route and back to
  `/`, rather than the SPA needing a separate "access denied" screen. `Dashboard.tsx` only renders
  the "Admin area" nav link under the same condition. This client-side behavior is a UX nicety,
  not the security boundary — that's `require_administrator` on the backend, which is what's
  actually tested against a Learner/Content Manager session getting a 403.
- `AdminOverview` calls `/api/admin/ping` on demand as a visible, clickable proof that the admin
  area's backend connection is live and restricted, mirroring the existing "check backend health"
  button pattern on the learner dashboard.
- All new UI strings (`admin.*`) are routed through `t()` with EN/DE translations.

## Notes

- No generic `require_role(name)` factory — `require_administrator` is the only role gate this
  release needs (Content Manager has no admin-only behavior in Release 0). Tickets 8–11 will need
  the same pattern for their own admin-only endpoints; generalizing it is a trivial follow-up when
  that need actually arrives rather than something to speculate about now.
- No audit logging here — ticket 4 ships no state-changing admin action, just the gate and a
  read-only stub.
