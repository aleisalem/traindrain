# Delete a module

Release 1, ticket 11. Content that must not exist any more is genuinely
gone — and the evidence that people were trained on it is not. Modelled
directly on Release 0's user-erase tombstone.

## What changed

- `DELETE /api/content/modules/{id}` sets `status` to `deleted` and stamps
  `deleted_at`, and purges everything that is genuinely content: every
  `module_pages` row, every `module_versions` row (its own stored objects
  removed from S3/LocalStack-S3 first), and every `module_assets` row and its
  stored object. `current_version_id` is cleared explicitly, ahead of the
  version rows going, rather than left to the FK's `ON DELETE SET NULL` to do
  implicitly. Every `assignments` row targeting the module's translation
  group is removed too — the material can never be newly assigned again.
- The `modules` row itself survives as the tombstone: `title`, `language`,
  and its timestamps stay exactly as they were, which is what lets a
  completion record still resolve and render as *"Phishing Awareness —
  deleted"* rather than a dangling reference. A new `deleted_version_number`
  column additionally captures whatever `current_version_id` pointed at
  just before the delete cleared it (its own version row is about to be
  gone) — the tombstone's own memory of its last version, independent of any
  one learner's `completed_version_number`, so even a module nobody ever
  completed still says what it was last published as. `null` for a module
  deleted while still an unpublished draft, which never had one.
  `module_progress` rows are never touched — they are a learner's own record
  of what they read, not the author's content.
- `deleted` is terminal, enforced by one new check —
  `ensure_module_editable` in `app/access.py` — that every other mutating
  authoring route asks before doing its own work: metadata edits, page
  create/update/delete/reorder, publish, duplicate (as the source), asset
  upload, translation linking (already had its own check from ticket 6), and
  assignment creation. Each refuses with 409 `module_deleted`. A second
  `DELETE` on an already-deleted module is 409 `already_deleted`.
- `GET /api/content/modules/{id}/deletion-impact` (`completion_count`) tells
  the confirmation dialog how many completion records the tombstone will
  carry, before the delete happens — the same "tell the author the number
  while the decision is still avoidable" shape ticket 4's
  `revision-impact` gives the publish dialog.
- A learner mid-module when it is deleted gets the same "no longer
  available" 404 an unpublished module already gives them: both are the same
  `status != "published"` branch in `may_read_module` and
  `_resolve_readable_variant`, so no new access-control path was needed.
  Their progress row is retained, and it goes on rendering under the
  tombstoned title in `GET /api/me/modules` (`module.title`, since the
  published snapshot it would otherwise read from is gone).
- `app.reporting.full_roster` gained an `include_unassigned_progress` flag
  (off by default, so a live module's report keeps meaning exactly what it
  always has). The Administrator report and CSV export pass it as
  `module.status == "deleted"`: since a delete removes every assignment on
  the material, the roster's usual assignment-driven membership would
  otherwise go empty the moment the evidence became relevant, so a deleted
  module's roster is additionally built from anyone with a `module_progress`
  row on it, with no due date since nothing targets them any more.
- Assignment targets a translation group, not a single language's text
  (ticket 7), so removing every assignment on the module's translation group
  also un-assigns a surviving sibling variant, if one exists, even though
  that sibling's own pages, versions, and assets are left completely
  untouched — the literal reading of "its assignments are removed" applied
  to the only scope assignments have. Ticket 11 doesn't special-case a
  multi-variant group; `test_deleting_one_variant_removes_the_shared_assignment_for_every_sibling`
  pins this down as a deliberate, tested property rather than an incidental
  one.
- `GET /api/content/modules` (no `status` filter given) now excludes
  `deleted` modules by default, so a tombstone doesn't clutter the authoring
  list — there is deliberately no `status=deleted` filter value to browse
  them back into view. Explicit `status=draft`/`status=published` filters
  already excluded them.
- `module_deleted` is audit-logged with the module id, its title, and the
  count of completion records affected.
- Frontend: a "Delete module" control on `ModulePublishPanel.tsx` opens
  `DeleteModuleDialog.tsx`, which fetches and states the completion count
  before the author can confirm. On success the screen navigates back to
  `/content`, since nothing on a deleted module is left to edit. If a
  deleted module's edit screen is reached anyway (a stale link), the panel
  collapses to a plain deleted-state message instead of the
  publish/unpublish/duplicate controls and the catalog-visibility toggle,
  none of which the server would accept any more.
- Backend tests in `tests/test_module_deletion.py`: pages, versions, and
  stored objects are all gone after a delete; the tombstone keeps its title,
  language, and timestamps; every other mutating authoring route refuses a
  deleted module; assignments are removed but progress and audit history
  survive and are not cascaded away; a mid-module learner sees the same
  "no longer available" state an unpublish already gives; a completion
  renders under the tombstoned title in both a learner's own list and an
  Administrator's report; only a Content Manager or Administrator may
  delete.
