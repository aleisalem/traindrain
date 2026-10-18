# Active-campaign edit safeguards

Release 2, ticket 6. A running campaign can be adapted without silently stranding learners.

## Additions are free

Adding a module or a target to an active (or suspended) campaign is an ordinary `PATCH`. Access is derived live (ticket 3), so it takes effect on the learner's next read. Nothing is emailed: only activation mails anyone, and a newly targeted learner is not mailed retroactively.

## Removals with progress need confirmation

`POST /api/content/campaigns/{id}/edit-impact` takes the same `modules` / `targets` full replacements a `PATCH` would and returns, without changing anything, `learners`, `records`, `completed`, a per-module breakdown and `requires_confirmation`. A *record* is a learner's progress row on a campaign module that stops being reachable through the campaign, because the module was removed or the learner is no longer targeted by any remaining target (someone still reached by another group is not counted). Drafts always report zero.

`PATCH` with such a removal and no `confirm_impact: true` is a **409 `impact_confirmation_required`** carrying the numbers; the confirmed update records them as `confirmed_impact` in its `campaign_updated` audit entry. Progress rows are never deleted. The builder asks the impact endpoint before saving a non-draft campaign and shows `CampaignImpactDialog` (count first, heading focused, not the confirm button).

## Deletion

Only a draft is deletable, by the creator or an Administrator. `draft` is the initial status and nothing returns to it, so a campaign that is anything else has been activated; it is a **409 `campaign_already_activated`**, for Administrators too.

## Modules deleted elsewhere

A module tombstoned by Release 1's delete stays in the campaign. The authoring view already reports `availability: deleted`; the learner view marks it `unavailable` (struck through, "Deleted — no longer required", no link). `compute_progress` skips tombstoned groups, so they never count toward mandatory completion and are never overdue.
