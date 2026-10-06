# Campaign drafts (Release 2, ticket 1)

A Content Manager builds a campaign in draft: a name, description, an ordered list of modules (each `mandatory` or `recommended`), group targets, optional start/due dates, and `auto_reminders` / `sequential` toggles. A draft is inert — invisible to learners, sends nothing. Activation and the rest of the lifecycle come in tickets 3–4.

## Backend

- Tables `campaigns`, `campaign_modules`, `campaign_targets` (migration `e7b3c91a4d26`). Modules are referenced by **translation group**, so a translation added later is covered. `target_id` is not a foreign key (user or group); existence is checked at the route, as for assignments.
- `GET|POST /api/content/campaigns`, `GET|PATCH /api/content/campaigns/{id}` (`app/routes/campaigns.py`). `created_by` and `status` are never accepted (`extra="forbid"` → 422). On `PATCH`, `modules` and `targets` are **full replacements** (list order = module order) and a date set to `null` clears it.
- **Visibility:** `may_see_campaign` is the single decision — today, the creator only. Everyone else (other Content Managers, Administrators) gets a **404, never a 403**, on every route. Learners get 403 from the Content-Manager gate. Ticket 2 widens this one function.
- **Individual targets** are a 403 for a Content Manager, both when adding and when stripping one. Groups are picked through the existing counts-only `GET /api/content/groups`; a person's name is only revealed to an Administrator.
- **Availability:** each module in a response reports `published`, `unpublished` or `deleted`. A draft may reference any of them; ticket 3 refuses activation on unpublished mandatory modules.
- Audit: `campaign_created`, `campaign_updated` (carrying the changed field names; a no-op patch logs nothing).

## Frontend

`src/frontend/src/features/content/`: `CampaignsPage.tsx` (list at `/content/campaigns`) and `CampaignBuilderPage.tsx` (`/content/campaigns/new`, `/content/campaigns/:campaignId`), with a "Campaigns" entry in the Content nav group (Content Managers and Administrators only).

UX brief: single page of stacked cards (Details, Modules, Targets) with one Save. Modules reorder by **drag-and-drop (native HTML5) and by up/down buttons** — the buttons are the keyboard and screen-reader path. Unpublished/deleted modules show a warning line. Individual targets that already exist are shown read-only and sent back unchanged; the Administrator individual-target picker arrives in ticket 2.

## Tests

`tests/test_campaigns.py` (permission matrix, 404-vs-403, validation, ordering, availability, audit); `CampaignBuilderPage.test.tsx`, `CampaignsPage.test.tsx`.
