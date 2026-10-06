# Campaign collaborators, Administrator reach and presence (Release 2, ticket 2)

The creator of a campaign invites other Content Managers to work on it; Administrators see and edit everything; everyone with a campaign open sees who else does.

## Backend

- Tables `campaign_collaborators` (`campaign_id`, `user_id`, `added_by`) and `campaign_edit_sessions` (migration `a4c8e1f27b53`). A collaborator row survives its creator being erased or losing the role, so working collaborators are never orphaned.
- **Visibility** (`may_see_campaign`, still the one decision): creator, collaborator, or Administrator. Everyone else gets a **404, never a 403**. **Management** (`may_manage_campaign`): creator or Administrator; a collaborator who attempts a management route gets a **403**.

| Action | Creator | Collaborator | Administrator | Other CM |
|---|---|---|---|---|
| See / edit metadata, modules, targets | yes | yes | yes | 404 |
| `POST /{id}/collaborators` (`{email}`), `DELETE /{id}/collaborators/{user_id}` | yes | 403 | yes | 404 |
| `DELETE /{id}` (draft only; else 409) | yes | 403 | yes | 404 |
| `POST /{id}/owner` (`{user_id}`, reassign creator) | 403 | 403 | yes | 404 |
| Individual targets (add or strip) | 403 | 403 | yes | 404 |

- Collaborators are added **by email**, so a Content Manager never browses the staff directory. The target must hold Content Manager or Administrator (else 409), not be erased (404), not already be on the campaign or its creator (409).
- Reassigning the creator requires the new owner to hold an authoring role (409), drops them from the collaborator list, and removes the previous creator from the campaign.
- Responses carry `collaborators` and `can_manage` (server-decided; the UI only mirrors it).
- Presence: `POST|DELETE /api/content/campaigns/{id}/editing`, the Release 1 module heartbeat (60s window, caller excluded) applied to campaigns.
- Audit: `campaign_collaborator_added`, `campaign_collaborator_removed`, `campaign_owner_changed`, `campaign_deleted`.
- Draft deletion is implemented here (creator or Administrator, status `draft` only); ticket 6 adds the "ever activated" rules.

## Frontend

`CampaignCollaboratorsPanel.tsx` (list for everyone; add/remove for `can_manage`; reassign-creator for Administrators), an Administrator-only individual-target picker in `CampaignBuilderPage.tsx` (the only place besides the panel that reads `/api/admin/users`, via `useAdminUserOptions`), presence avatars via the shared `useEditors` hook and `ModuleEditorsPresence`, and a "Delete draft" button for `can_manage`.

## Tests

`tests/test_campaign_collaborators.py` (every matrix row, orphan handling, presence, audit); `CampaignBuilderPage.test.tsx` (panel, Administrator gating, presence).
