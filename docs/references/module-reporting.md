# Reporting: completion report and CSV roster

Release 1, ticket 9. Two different answers to "did people do the training?",
chosen by the server rather than the UI, so a Content Manager can never reach
a colleague's identity through a report even if the frontend were rewritten.

## What changed

- `GET /api/content/modules/{id}/report` — one URL, two response shapes,
  decided by `is_administrator(caller)` in `app.routes.reports`. A Content
  Manager gets `ContentManagerModuleReport`: per-**group** counts (completed,
  in progress, not started, overdue), never a name or email. An Administrator
  gets `AdministratorModuleReport`: the full roster, one row per targeted
  learner, with their name, email, completion state, the version they
  completed, and their due date. `response_model=None` on the route is
  deliberate — FastAPI serializes whichever of the two models the function
  actually returns, rather than filtering both through one shared schema that
  would have to be their lowest common denominator.
- `GET /api/content/modules/{id}/report.csv` — Administrator-only, on its own
  route rather than a format flag on the endpoint above, so the 403 boundary
  for a Content Manager is a route-level `Depends`, not a branch a review
  could miss.
- `app.reporting` is the shared walk both routes use: `group_standings`
  (Content Manager) scopes to **group-type** assignments only — an
  individually-targeted learner (Administrator-only, see `Assignment`'s own
  docstring) never appears in a group's aggregate, because that would turn
  the aggregate into a one-person aggregate identifying them by elimination.
  `full_roster` (Administrator) walks every assignment on the module's
  translation group, group or individual, deduplicated by learner with the
  nearest due date winning across whichever assignment(s) name them — the
  same tie-break `app.assignments.nearer_due_date` (renamed from the
  previously-private `_nearer` so both modules could share it) applies from a
  single learner's own side.
- A learner's `LearnerState` is `completed`, `in_progress`, or `not_started`,
  computed from their `ModuleProgress` row: `completed` only when
  `completed_at` is set **and** `superseded_at` is `None`. A completion a
  substantive republish superseded (ticket 4/7) reports as `in_progress` —
  outstanding again — while `completed_at` and `completed_version_number`
  stay on the row and on the response, so the roster can still say what the
  person read and when even while showing them as not currently done.
  `overdue` is not a fourth, exclusive bucket: it is true whenever a
  not-completed learner is past their due date, exactly what
  `app.assignments.is_overdue` already means for a learner's own list —
  the same deployment-timezone "today" (`app.security.system_settings
  .deployment_today`) both readings use.
- Figures are counted across the whole translation group, not one language
  variant — the same scope `ModuleProgress` and `Assignment` are already keyed
  on, so a mixed-language workforce reports as one population.
- Both a group's members and an individual target are filtered to
  `disabled_at is None and erased_at is None` before they are counted or
  listed — the same "who is really targeted right now" filter assignment
  notification and reminders already apply.
- Frontend: `ModuleReportPanel.tsx` (rendered on `/content/{id}`, after the
  assignment panel) and `useModuleReport.ts`. The panel branches on which
  shape came back (`"groups" in report`) rather than on the `isAdministrator`
  prop — the server's response is the source of truth, the prop only decides
  whether the CSV export link is offered. `report.csv` is a plain `<a href>`,
  followed by the browser with the existing session cookie, the same pattern
  an asset download already uses.

## Why two routes, not one with a `role` check duplicated in three places

The earlier drafts considered branching the CSV export inside
`get_module_report` on an `Accept` header or a `?format=csv` query param.
Both would have meant a Content Manager's 403 living inside a shared handler
that also has to remember, on every future change, not to leak a name into
the aggregate path. A dedicated `require_administrator`-gated route makes
that boundary the same kind of route-level `Depends` every other
Administrator-only action in this codebase already uses.
