# Sequential campaigns

Release 2, ticket 5. A campaign marked `sequential` unlocks its modules one after another.

## How the sequence is specified

There is no separate ordering field. The sequence is the campaign's ordered module list (`campaign_modules.position`, set in the builder by drag-and-drop or the arrow buttons), and the `sequential` checkbox switches enforcement on. The builder shows a hint under the checkbox saying so. Module N waits on module N−1 in that list; recommended modules take part in the chain like mandatory ones.

## Server-side enforcement

`app.campaigns.campaign_access` returns `open` (readable through a campaign) and `locked` (group → the prerequisite group in front of it). A sequential module with an incomplete predecessor is simply left out of `open`, so every consumer of the single access decision refuses it with no lock-specific code:

- `GET /api/me/modules/{group}`, page `view`, and `complete` return **403 `module_locked`** carrying `prerequisite_translation_group_id` — no pages, no attachments. (The learner is targeted by the campaign, so revealing the lock is not a leak; anything else stays a 404.)
- Asset delivery (`authorize_asset_access`) keeps returning 404 for the locked module's files.

"Complete" is `is_current_completion` — the same notion the campaign progress bar uses — so a completion superseded by a substantive republish relocks the successor, and later quiz-gated completions feed it unchanged. A predecessor with nothing published (draft, tombstone) cannot be completed, so the lock skips to the nearest earlier module that can; one withdrawn module never locks the rest forever.

## Other routes are exempt

The lock applies only to the campaign's own route. A module also reachable through the open catalog or a direct/group assignment stays readable, and is reported as not locked. A closed campaign keeps only what was already started and imposes no locks; suspended campaigns contribute no route at all (ticket 4).

## Learner API

`GET /api/me/campaigns`: each campaign carries `sequential`; each module carries `locked`, `prerequisite_translation_group_id`, and `prerequisite_title`.

## Frontend

`CampaignCard.tsx` renders a locked row as plain text "Locked — finish “X” first" (a lock glyph hidden from screen readers; no link, so nothing focusable leads nowhere). `ModuleViewerPage.tsx` shows a "This module is locked" state with a link to the prerequisite when the URL is typed directly. EN/DE strings added.

## Tests

`tests/test_campaign_sequential.py`: lock by URL, page view and attestation, asset delivery, unlock on completion, superseded relock, catalog-route exemption, non-sequential campaigns, unpublished predecessor, closed campaigns. Frontend: locked rendering in `MyLearningPage.test.tsx`, locked viewer in `ModuleViewerPage.test.tsx`.
