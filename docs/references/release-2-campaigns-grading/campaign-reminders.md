# Campaign reminders

Release 2, ticket 7. A learner is chased once per campaign, not once per module.

## Scheduled job

`python -m app.jobs.send_reminders` (the same entrypoint as Release 1) now also calls `run_scheduled_campaign_reminders` (`app/reminders.py`), before the per-module run. A campaign is reminded when it is `active`, has `auto_reminders` on and a `due_date`, and today (deployment timezone) lands on the existing cadence: 7 days before, 1 day before, the due date, then weekly while overdue. Each currently-targeted learner gets **one** email listing the mandatory modules they still owe, in their `preferred_language`. Recommended modules, deleted modules, modules with nothing published, and current completions are left off; a completion superseded by a substantive republish counts as owed. Nothing is sent when nothing is owed.

## Send log and the cap

New table `campaign_reminders` (migration `c5a8f3d1e7b2`): `campaign_id`, `user_id`, `kind`, the `translation_group_ids` that email listed, `sent_at`. It is the campaign half of the send log; `module_reminders` is the other.

- A second run the same day sends nothing (a row exists for that campaign and learner).
- A module's Release 1 reminder is suppressed when a campaign email already listed that module to the learner today (`_already_reminded_today`).
- In the other direction, a module already chased today (by the module path or the manual module nudge) is left off the campaign email, so a learner is reached once per module per day whichever path runs first.

## Suspended, closed, resumed

Only `active` campaigns are considered, so suspended and closed ones send nothing. The cadence matches exact days, so resuming never produces a catch-up burst; the next checkpoint that falls on a day the job runs applies.

## Manual nudge

`POST /api/content/campaigns/{id}/remind` — Administrator only (403 otherwise; 404 unknown id; 409 `campaign_not_active` unless active). Same audience as the scheduled run (a campaign with reminders off or no due date reaches nobody) and the same per-learner cap. Limited to once per campaign per day (429 `reminder_already_sent_today`), checked against the campaign's own `reminder_sent` audit entry — written on every successful call, including one reaching nobody. Returns `{"sent_count": N}`, the learners actually reached.

## Frontend

`CampaignLifecyclePanel.tsx`: an Administrator-only "Remind everyone outstanding" button on an active campaign, reporting the real reach or the day's rate limit. EN/DE strings added.
