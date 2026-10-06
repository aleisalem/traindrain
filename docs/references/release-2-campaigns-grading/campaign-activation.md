# Campaign activation and the learner's campaign view

Release 2, ticket 3. A campaign author takes a draft live; targeted learners see it under "My learning".

## Lifecycle

`POST /api/content/campaigns/{id}/activate` (draft → active) and `.../close` (active → closed). Anything else is a 409 `invalid_transition`. Whoever may edit the campaign (creator, collaborator, Administrator) may use them; non-participants get a 404.

Activation is refused with a **422** `campaign_not_activatable` unless every `mandatory` module has a published variant (`unpublished_modules` lists the translation groups) and at least one target exists (`no_targets`). Unpublished `recommended` modules do not block it.

On activation each currently-targeted, enabled learner gets one email in their `preferred_language` (`send_campaign_activation_email`), deduplicated across overlapping group/individual targets. The audience is resolved once, so a learner joining later is not emailed retroactively. Emails are sent before the commit, as for assignments.

## Access: the campaign branch

`may_read_module` (`app/access.py`) takes a `campaign_group_ids` set alongside `assigned_group_ids`. `app.campaigns.campaign_translation_group_ids` builds it per request: all modules of **active** campaigns that target the user (directly or via current group membership), plus — for **closed** campaigns — only modules the learner already has a progress row for. So closing stops new starts while earlier work stays readable. Learner routes (`LearnerReach` in `app/routes/learning.py`) and asset delivery (`authorize_asset_access`) both ask this one decision. Nothing is expanded or stored: a late joiner gets access, a leaver loses it but keeps their progress rows.

## Learner view

`GET /api/me/campaigns` returns each campaign (active; closed only if the learner has progress in it) with `required_total`, `required_done`, `complete`, `due_date`, `overdue`, and its modules in order with `requirement`, `state` (`not_started` | `in_progress` | `completed`), `available` and `overdue`. Completion is computed live in `app.campaigns.compute_progress` from `module_progress`; a completion superseded by a substantive republish does not count, so it reopens the campaign. A campaign with no mandatory modules is never "complete". `overdue` is never true for a closed or complete campaign. `GET /api/me/modules` is unchanged.

## Daily job

`python -m app.jobs.send_reminders` first runs `activate_due_campaigns`: drafts with `start_date <= today` (deployment timezone) are activated — same checks and emails as the manual route, `trigger: "start_date"` in the audit entry. A campaign that is not ready (unpublished mandatory module, no targets) stays draft and is retried next run. The status flip makes reruns no-ops; each campaign commits separately so one failure doesn't block the rest.

## Audit

`campaign_activated` (with `trigger`, `learners_notified`) and `campaign_closed`.

## Frontend

`src/frontend/src/features/content/CampaignLifecyclePanel.tsx` (activate/close in the builder, refusal reasons shown); `src/frontend/src/features/learning/CampaignCard.tsx` and `MyLearningPage.tsx` (campaign groups, progress bar, mandatory/recommended and overdue labels; modules already inside a campaign are not repeated below). EN/DE strings added.

## Not in this ticket

Suspend/resume (ticket 4), sequential locking (5), edit safeguards and tombstone markers (6), campaign reminders (7).
