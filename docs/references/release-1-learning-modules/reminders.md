# Reminders: scheduled job, manual nudge, per-day cap, timezone setting

Release 1, ticket 8. Required training gets chased without becoming noise —
a daily cadence, an Administrator's immediate nudge, and one hard rule both
paths obey: at most one email per learner per module per day.

## What changed

- New `module_reminders` table: `assignment_id`, `user_id`, `kind`
  (`advance_7`|`advance_1`|`due`|`overdue_weekly`|`manual`), `sent_at`. One
  row per email actually sent — never per attempt — and what both paths
  consult before sending: it is what makes a second run of the job on the
  same day a no-op, and what the daily cap is checked against.
- `app/reminders.py` (new): the shared domain logic behind both paths.
  - `scheduled_kind_for_due_date` decides the cadence: 7 days before, 1 day
    before, on the due date, then weekly for as long as it stays overdue.
    Only `mandatory` assignments with `auto_reminders` on and a `due_date`
    set are ever eligible — a `recommended` assignment has no deadline to
    count down to, and one with reminders off is left alone entirely
    (`_AUTO_REMINDER_ELIGIBLE`).
  - `run_scheduled_reminders` is the daily job: every eligible assignment
    that lands on a cadence checkpoint today gets its outstanding learners
    (not already completed and current, not already reminded today) emailed
    once.
  - `send_manual_reminders` is the Administrator's nudge, scoped to one
    module's translation group. It targets the exact same audience the
    scheduled cadence would — not every assignment ever made against the
    material — so a nudge never reaches someone whose author deliberately
    left reminders off.
  - `_already_reminded_today` is the per-learner cap: it joins
    `module_reminders` back to `assignments` on `translation_group_id`, so a
    group assignment and an individual assignment that both happen to name
    the same learner still only ever reach them once a day.
  - `ReminderWindow` / `deployment_day_bounds` resolve "today" and the
    UTC-comparable instants it spans, from the deployment timezone setting
    below.
- `POST /api/content/modules/{id}/remind` (in `app/routes/assignments.py`) —
  **Administrator-only**. Rate-limited to once per module per day, checked
  against the `reminder_sent` **audit entry**, not `module_reminders` — the
  route writes that entry on every successful call, including one that
  reaches nobody (everyone already capped today, or nothing published yet),
  while a `module_reminders` row only exists when an email actually went
  out. Checking the send-log instead would have let a zero-reach call slip
  past the "once per module per day" rule indefinitely.
  (`_manual_nudge_already_invoked_today` in the same file.)
- Deployment-wide timezone: `system_settings.reminder_timezone` (default
  `Europe/Berlin`), read/set through `GET|PUT
  /api/admin/settings/reminder-timezone` — the same pattern Release 0 used
  for invite expiry, validated against the IANA tzdata database itself
  (`ZoneInfo`), not a regex. `app.assignments.is_overdue` now takes an
  explicit `today` argument sourced from this same setting
  (`system_settings.deployment_today`), so "overdue" on a learner's own My
  Learning list and "due today" for the reminder cadence are the same
  moment, per the docstring `is_overdue` carried since ticket 7.
- `send_reminder_email` (`app/security/mailer.py`) — subject and body render
  in the recipient's `preferred_language`, with wording that varies by
  cadence kind (advance/due/overdue/manual).
- `app/jobs/send_reminders.py`: `python -m app.jobs.send_reminders` — the
  literal entrypoint a production scheduled task will invoke (ticket 14).
  `docker-compose.yml` gains a `reminder-runner` service that loops that same
  command locally, standing in for a scheduler without emulating one; the
  job's own idempotency is what makes the hourly local loop harmless.
- Frontend: an Administrator-only "Remind everyone outstanding" button on
  `AssignmentsPanel.tsx`, reporting how many learners were actually reached
  (translated, pluralized) or the day's rate-limit message on a 429. Not in
  this ticket's original scope, but small enough to add alongside the
  endpoint it calls.

## Why the manual endpoint's rate limit isn't the send-log

The two checks in this ticket look similar but answer different questions.
`_already_reminded_today` answers "has *this learner* had an email about
*this module* today" — true only once a `module_reminders` row exists for
them. `_manual_nudge_already_invoked_today` answers "did an Administrator
already run this button today" — a fact about the *action*, not about any
particular send. A module where the scheduled job already reached everyone
mandatory-and-eligible today is a nudge with nothing left to do: zero emails,
`sent_count: 0`, and no `module_reminders` row written. Keying the button's
own rate limit on that table would have let it be pressed an unlimited number
of times on such a day — each call correctly harmless, but the endpoint
itself never actually rate-limited, contradicting its own contract. The
`reminder_sent` audit entry doesn't have that gap, because the route writes
it unconditionally after every non-rate-limited call.

## What's still open

Ticket 14 (infrastructure) still owes the real scheduled trigger — an
EventBridge Scheduler rule plus the ECS task definition invoking
`python -m app.jobs.send_reminders` — and the SES templates for these emails.
Locally, `reminder-runner`'s hourly loop is the stand-in.
