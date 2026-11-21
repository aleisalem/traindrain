# Campaign reports

"Did people do this programme?" with the Release 1 privacy split, decided on the server.

- `GET /api/content/campaigns/{id}/report` — visible to exactly the people who may edit the campaign
  (creator, collaborators, Administrators); anyone else gets a 404.
  - **Content Manager**: per targeted *group* — members, completed, in progress, not started,
    overdue, suspended, and average progress (mean % of mandatory modules complete). Never a name or
    email; individually-targeted learners are left out so an aggregate cannot identify one person.
  - **Administrator**: the per-learner roster — name, email, state, overdue, progress, and each
    module's state (with the prior `completed_at`/version kept for a superseded completion).
- `GET .../report.csv` — Administrator-only (403 otherwise); one row per learner, one column per
  module; text cells are neutralised against spreadsheet formula injection.
- Counts reuse the learner view's live completion (`is_current_completion`, `compute_progress`), so a
  superseded completion reports as outstanding; modules deleted elsewhere are marked unavailable and
  not required. The four learner states (completed / in progress / not started / suspended) are
  mutually exclusive; `overdue` is an overlay and is frozen false while the campaign is suspended or
  closed.
- Code: `app.reporting` (`campaign_group_standings`, `campaign_full_roster`), `app.routes.reports`.
- Frontend: `CampaignReportPanel.tsx`, shown in the campaign builder once a campaign is live and under
  the "Campaigns" tab of the Reports area (`CampaignReportsSection.tsx`); the CSV link is
  Administrator-only.
