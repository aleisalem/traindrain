# Campaign suspend and resume

Release 2, ticket 4. An author pauses an active campaign and later resumes it.

## Lifecycle

`POST /api/content/campaigns/{id}/suspend` (active → suspended) and `.../resume` (suspended → active). Any other transition is a 409 `invalid_transition`. Whoever may edit the campaign (creator, collaborator, Administrator) may use them; non-participants get a 404. Closing still requires `active`, so a suspended campaign is resumed before it can be closed.

## What suspension removes

Only the campaign's own route to a module. `campaign_translation_group_ids` (`app/campaigns.py`) already considered only active campaigns (and started modules of closed ones), so a suspended campaign contributes nothing to `may_read_module` — no change to the access decision itself. A module still reachable through the open catalog or a direct/group assignment stays readable as a normal module; one with no other route returns 404.

- `GET /api/me/campaigns` no longer lists a suspended campaign (so it is never reported overdue).
- `GET /api/me/modules` omits a started module whose only route is a suspended campaign (`suspended_translation_group_ids`, minus anything still `available`). It reappears on resume.
- Progress rows are never touched.

Reminders do not exist for campaigns yet (ticket 7); when they do they must skip `suspended`.

## Resume past the due date

Due dates never shift on their own. Resuming always succeeds; if `due_date` is before today (deployment timezone) the campaign gets `due_date_lapsed = true` (new column, migration `b9d4e2a6c1f8`), returned in `CampaignResponse`. A `PATCH` setting `due_date` to today or later — or clearing it — resets the flag; another past date does not. The flag is stored rather than derived because a campaign that merely ran past its deadline is overdue, not lapsed.

## Audit

`campaign_suspended`; `campaign_resumed` (with `due_date_lapsed`). Clearing the flag via PATCH is recorded in that `campaign_updated` entry's changed fields.

## Frontend

`CampaignLifecyclePanel.tsx`: Suspend button on an active campaign, Resume on a suspended one, and a persistent alert with a date picker ("Set due date") whenever `due_date_lapsed` is true. The builder keeps its own due-date field in step. EN/DE strings added.
