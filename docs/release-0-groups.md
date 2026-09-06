# Release 0 — Groups: CRUD, membership, invite group pre-assignment

Implements ticket 11 of Release 0 (`.scratch/release-0-foundation/tickets.md`).

## What changed

- New `Group` model (`id`, `name` unique, `description`, `created_at`) and a
  `group_members` association table, mirroring the existing `Role`/`user_roles`
  shape. `User.groups` is a `lazy="selectin"` many-to-many, same as `User.roles`.
- Admin-only, Administrator-gated endpoints under `/api/admin/groups`:
  - `GET /api/admin/groups` / `POST /api/admin/groups` — list / create (409 on
    a case-insensitive duplicate name).
  - `PUT /api/admin/groups/{group_id}` — rename/redescribe (404 unknown group,
    409 duplicate name).
  - `DELETE /api/admin/groups/{group_id}` — deletes the group; `group_members`
    and `invite_groups` rows for it cascade at the database level
    (`ON DELETE CASCADE`), so no orphaned membership or invite-pre-assignment
    rows are left behind.
  - `GET /api/admin/groups/{group_id}/members` — same shape as
    `GET /api/admin/roles/{role_id}/members` (ticket 10).
  - `POST`/`DELETE /api/admin/groups/{group_id}/members/{user_id}` — add/remove
    a member (404 unknown group/user, 409 already-member/not-a-member; adding
    an erased user is also a conflict, removal isn't — same erasure-tombstone
    convention as role assignment in ticket 10).
  - Unlike role assignment, group membership changes do **not** revoke the
    target's other sessions — groups are an organizational grouping for
    targeting future learning campaigns, not an access-control mechanism, so
    there's no permission change to enforce immediately.
  - All five mutating actions are audit-logged (`group_created`,
    `group_updated`, `group_deleted`, `group_member_added`,
    `group_member_removed`).
- `POST /api/admin/invites` (ticket 5) accepts an optional `group_ids` list
  alongside the existing `role_ids`; `POST /api/invites/{token}/accept`
  assigns the invite's pre-selected groups to the new user, the same way it
  already applies pre-selected roles.
- Frontend: `features/admin/AdminGroupsPage.tsx` (`/admin/groups`, linked from
  `AdminShell` as "Manage groups") — a create-group form plus one card per
  group with inline rename/redescribe, a two-step delete confirmation
  (matching the erase-user precedent from ticket 9), its member list with a
  per-member "Remove" button, and a select-and-add control for non-members.
  `InviteUserPage.tsx` gained a "Groups" checkbox fieldset alongside the
  existing roles one.
- `UserListItem` (`app/schemas/users.py`, used by `GET /api/admin/users`,
  `GET /api/admin/roles/{id}/members`, and `GET /api/admin/groups/{id}/members`)
  gained a `groups: list[str]` field alongside the existing `roles` one, and
  the three near-identical construction sites in `app/routes/admin.py` were
  collapsed into one `_to_user_list_item` helper. This lets
  `AdminGroupsPage.tsx` compute each group's members/eligible-users client-side
  from a single `GET /api/admin/users` call — the same single-fetch pattern
  `AdminRolesPage.tsx` already uses for roles — instead of the N+1
  `GET /api/admin/groups/{id}/members` fan-out an earlier version of this page
  made per group on load.

## Notes

- A fix landed alongside this ticket: `_get_target_user` in `app/routes/admin.py`
  used `db.get(User, user_id)`, which returns an already-identity-mapped row
  as-is without applying the mapper's `selectin` eager loads. That's invisible
  in production (each request gets a fresh session), but broke on `User.groups`
  the moment a test's shared session touched the same row twice — once to seed
  it, then again from a route handler — before `groups` had ever been loaded,
  raising `MissingGreenlet` on the first lazy-load attempt. Replaced with an
  equivalent `select(User).where(User.id == user_id)`, which reliably applies
  eager loads regardless of identity-map state.
- No endpoint returns "all groups a user belongs to" from the user's own side
  (`UserListItem` doesn't carry a `groups` field) — the admin UI instead asks
  each group for its member list, mirroring how `AdminRolesPage` already
  cross-references `GET /api/admin/roles` and `GET /api/admin/users` rather
  than adding a redundant read endpoint.
