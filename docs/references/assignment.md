# Assignment: groups, individuals, due dates, emails, the learner's assigned list

Release 1, ticket 7. Content reaches the people who have to read it, without
turning module authoring into a route into the staff directory.

## What changed

- New `assignments` table: `translation_group_id` (never a bare module —
  adding a translation later is covered automatically), `target_type`
  (`user`|`group`), `target_id` (not a foreign key — it names a row in one of
  two tables depending on `target_type`, checked at the route instead), an
  optional `due_date`, a required `requirement` (`mandatory`|`recommended`),
  and `auto_reminders` (default on). Unique on
  `(translation_group_id, target_type, target_id)` — assigning the same
  target twice is a 409, not a second round of emails.
- `GET|POST /api/content/modules/{id}/assignments` and
  `DELETE /api/content/assignments/{id}` — scoped to the module's translation
  group, so any of its language variants shows the same list.
  `target_type: "user"` is a 403 for anyone but an Administrator, on both
  creation and removal.
- **Membership is not expanded at assignment time.** The row names a group or
  a person; a learner's list is computed against their *current* group
  memberships on every read (`app.assignments.assignments_for_user`). A user
  added to a targeted group afterwards sees the module with no change to the
  assignment; one removed from it loses the assignment but keeps whatever
  progress they already made — the progress row was never keyed on the
  assignment (ticket 5) for exactly this reason.
- `GET /api/content/groups` — group names, descriptions, and member **counts**
  only. Exists so a Content Manager assigning a module never has a reason to
  call `/api/admin/groups/{id}/members`. The assignment list itself carries
  the same restraint: a group target's name is always shown (a Content
  Manager already sees that much), but a user target's name (`AssignmentTarget.name`)
  is `null` unless the caller is an Administrator — the raw `target_id` is
  still returned, but a UUID is not a colleague's name.
- `may_read_module` (`app/access.py`) gained a second learner branch: a
  published module is readable if it is catalog-visible *or* its translation
  group is in the caller's `assigned_group_ids` — a frozenset the caller
  builds once per request via `app.assignments.assigned_translation_group_ids`
  and passes in, never looked up per module. Every call site — the learner
  routes in `app.routes.learning` and `authorize_asset_access` in
  `app.routes.assets` — was updated to build and pass it, so an image inside
  an assigned module is reachable by exactly the same people as the page
  around it.
- On assignment creation, every currently-targeted learner is emailed once, in
  their own `preferred_language`, via `send_assignment_email`
  (`app/security/mailer.py`) — SES in production, LocalStack SES locally,
  exactly the invite/password-reset pattern. A learner who joins the group
  later is not emailed retroactively; they simply see the module on their next
  visit.
- `GET /api/me/modules` now returns the union of what a learner has touched
  (their `module_progress` rows) and what is assigned to them but not yet
  opened — resolved through the same variant-picking logic
  (`_pick_variant`) the viewer itself uses, so the title and language shown
  match what they would actually be given. Rows are deduplicated by
  translation group; when more than one assignment covers the same group (a
  direct one and a group one, say), the one with the nearest due date wins
  (`app.assignments._nearer`) — a defined due date always beats no due date.
  Every row carries `due_date`, `requirement`, and a server-computed
  `overdue` flag that is never true for a completed row, whatever the date
  says.
- `assignment_created` and `assignment_removed` audit entries.
- Frontend: `AssignmentsPanel.tsx` and `useAssignments.ts`, shown on
  `/content/{id}`; the individual-target radio only renders for a caller
  holding the Administrator role, mirroring the server's own check.
  `MyLearningPage.tsx` renders the not-started assigned rows alongside
  started and completed ones, with a due-date line that turns red when
  `overdue` is true.

## What "today" means, for now

`is_overdue` compares a due date against `datetime.now(UTC).date()`. Ticket 8
introduces a deployment-wide timezone setting for what "due today" means for
the reminder job's cadence; this is the one place in this ticket that will
need to switch to reading it. Nothing here schedules a reminder — that is
ticket 8's job, once a live assignment (this ticket) exists to scope it.
