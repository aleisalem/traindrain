# Release 0 — Role assignment management + session invalidation on role change

Implements ticket 10 of Release 0 (`.scratch/release-0-foundation/tickets.md`).

## What changed

- `GET /api/admin/roles/{role_id}/members`: lists the users holding a given
  role (same shape as `GET /api/admin/users`' rows), Administrator-only, 404
  on an unknown role. Added alongside `GET /api/admin/roles` (existing) so
  "view which roles exist and who holds each" is answerable as two atomic
  reads, independent of the admin UI (per the project's scoped-API-token
  convention) rather than only by cross-referencing the full user list
  client-side.
- `POST /api/admin/users/{user_id}/roles/{role_id}`: assigns a role to a
  user, Administrator-only. 404 if the user or role doesn't exist, 409 if
  the user already holds the role or has been erased — erasure is
  permanent, so a tombstone should never gain a new grant.
- `DELETE /api/admin/users/{user_id}/roles/{role_id}`: removes a role from a
  user (404 unknown user/role, 409 not held). Unlike assignment, this is
  allowed on an erased account: `erase_user` (ticket 9) never clears role
  membership, so this is the only way to strip a stale role left on a
  tombstone.
- Both endpoints revoke every one of the target's other active sessions —
  `revoke_other_sessions` from the existing session-lifecycle helper
  (`app/security/sessions.py`), already used by password change and 2FA
  recovery — so an access change takes effect immediately rather than
  waiting for the target's next login. Unlike disable/erase (ticket 9), an
  admin *can* change their own roles; when `user_id` is the acting admin's
  own id, the session performing the request is kept alive (`keep_session_id`
  set to the current session), matching the ticket's explicit "not the
  session performing the action, if it's their own" requirement.
- Both actions are audit-logged (`role_assigned`, `role_removed`) with the
  role name in the detail blob.
- No new "view roles with their members" endpoint: `GET /api/admin/roles`
  (existing, used by the invite-creation UI) and `GET /api/admin/users`
  (existing, ticket 9) already carry everything needed — the frontend
  cross-references them rather than duplicating an atomic read endpoint.
- Frontend: `features/admin/AdminRolesPage.tsx` (`/admin/roles`, linked from
  `AdminShell` as "Manage roles") — one card per role, listing its current
  members with a per-member "Remove" button, plus a select-and-assign
  control for users who don't yet hold the role. No confirmation step for
  either action (unlike erase in ticket 9): both are reversible, matching
  the disable/enable precedent rather than the irreversible-erase one.

## Notes

- Assigning/removing a role that leaves a user with zero roles, or removing
  the last Administrator's own Administrator role, is intentionally not
  specially guarded — not called for by the ticket, and out of scope for
  this pass.
