# Unified navigation shell, role-based landing, and merged preferences

A cross-cutting UI change: one navigation chrome instead of three, a homepage
that depends on the signed-in user's role instead of a shared placeholder,
and a single Preferences page instead of profile settings and two-factor
authentication living on separate screens.

## What changed

- `AppShell` (`src/frontend/src/shell/AppShell.tsx`) replaced the three
  near-identical shells `AdminShell`, `ContentShell`, and `LearningShell` —
  each used to render its own header, nav, and logout button. The new shell
  wraps `/admin`, `/content`, `/modules`, and `/profile` as a single React
  Router layout route.
- Its nav shows the **union** of what a user's roles unlock, not just their
  "primary" role: every authenticated user holds Learner (invite acceptance
  auto-assigns it), so "My learning"/"Browse catalog" are always present;
  "Content area" appears for Content Managers and Administrators
  (`canAuthorContent`); "Admin area" only for Administrators. Which groups
  render is computed in `src/frontend/src/shell/navConfig.tsx`.
- Nav placement — left sidebar or top bar — is a per-user preference, not a
  fixed layout choice. `PATCH /api/profile/preferences` gained a third field,
  `nav_position: "left" | "top"` (new `users.nav_position` column, migration
  `1a2b3c4d5e6f`), defaulting to `left` until the user picks otherwise from
  the Preferences page.
- The profile control in the nav (initials avatar — there's no photo-upload
  feature yet, so this is always the fallback state) opens `/profile`, which
  is now a single **Preferences** page: name, password, language/theme,
  navigation placement, and two-factor authentication (enroll/disable,
  recovery codes) all in one place. `TwoFactorSettings` used to be rendered
  on the old dashboard, disconnected from the rest of profile self-service.
- Signing in lands a user on the highest-privilege area they hold —
  Administrator → `/admin`, Content Manager → `/content`, otherwise →
  `/modules` (`getLandingPath` in `navConfig.tsx`) — rather than a shared
  placeholder dashboard. `Dashboard.tsx`, and the backend-health-check button
  it rendered, are gone. `GET /api/health` itself is untouched — it's an
  infrastructure/monitoring endpoint, not a UI feature.

## Not in scope

- Profile photo upload — the avatar always shows initials. Adding real photo
  upload is a separate feature (storage, validation, moderation) and wasn't
  requested here.
- A dedicated mobile nav (hamburger menu, collapsible rail). The shell is
  responsive at phone width but doesn't yet collapse the sidebar/top bar into
  a mobile-specific pattern.
