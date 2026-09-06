# Release 0 — User profile self-service

Implements ticket 12 of Release 0 (`.scratch/release-0-foundation/tickets.md`).

## What changed

- `PATCH /api/profile/name`: a logged-in user updates their own first/last
  name. Request schema uses `extra="forbid"`, so an attempt to also send
  `email` in the same payload fails validation (422) rather than being
  silently ignored — email stays immutable and isn't a field this endpoint
  accepts at all. Blank (or whitespace-only) names are rejected the same way.
- `PATCH /api/profile/preferences`: sets the user's `preferred_language`
  (`en`/`de`) and `preferred_theme` (`light`/`dark`/`colorblind`), persisted
  on the `users` row (both columns already existed, unused, from the ticket 2
  schema). Both fields are required together rather than independently
  optional, avoiding any ambiguity about whether omitting one means "leave
  unchanged" or "clear it." `GET /api/auth/me` now reports both.
- Changing your own password reuses the existing
  `POST /api/auth/change-password` endpoint (ticket 3) as-is — it already
  worked for any authenticated user, not just one under a forced
  first-login change, and already applies the ticket 2 policy validator and
  invalidates the caller's other active sessions. No backend change needed
  for that bullet.
- Neither new endpoint is audit-logged, matching the existing precedent for
  self-service password change — audit logging in this codebase is reserved
  for admin actions taken on another user's account, not a user's own data.
- Frontend: `preferredLanguage`/`preferredTheme` were threaded end-to-end —
  `useAuth`'s `AuthUser`/`MeResponseBody` types, a new
  `features/profile/ProfilePage.tsx` (`/profile`, linked from the dashboard)
  with three sections (name, password, language/theme), and
  `theme/useTheme.ts`, which changed from a session-only local `useState`
  hook to `useAppliedTheme(theme)` — a pure DOM-effect hook that just applies
  whatever theme it's given. Deciding *which* theme that is (the user's
  server preference, falling back to `prefersDarkDefault()` for a user with
  none — never colorblind by default) now happens once, in `App.tsx`'s
  `AuthenticatedRoutes`, so it's consistent across every authenticated
  screen rather than only wherever a switcher happened to be mounted.
  Language preference is applied the same way, via an effect that calls
  `i18n.changeLanguage()` whenever `user.preferredLanguage` changes.
- The dashboard's old inline language/theme switcher (session-only, present
  since the ticket 1 scaffold) was removed in favor of the profile page —
  it was explicitly a placeholder pending server-side persistence per its
  own code comment.

## Notes

- Picking a language or theme on the profile page calls
  `PATCH /api/profile/preferences` immediately (no separate save step),
  matching the instant-apply feel of the removed dashboard switcher; the
  visible theme/language change follows once the round trip completes and
  refreshes `/api/auth/me`, rather than being applied optimistically
  client-side before the server confirms it.
