# TrainDrain Roadmap

This roadmap breaks down the app description in [AGENTS.md](../AGENTS.md) into a sequence of releases. Each release is scoped to be small enough to run individually through the project process (`grilling` → `to-spec` → `to-tickets` → `implement` → `code-review`).

## Foundational decisions

These apply across all releases and were settled before sequencing:

- **Single-tenant per deployment.** No `Organization` entity or cross-org data isolation. "Different organizations" (AGENTS.md point 7) means separately themable deployments, not one platform serving many orgs.
- **Roles vs. Groups are distinct concepts.**
  - **Roles** govern access to system functionality (read-only / read-write / none per action). Administrators manage roles and their membership.
  - **Groups** describe a user's organizational role/task (e.g. "Backend Developers", "Office Management") and are the targeting unit for campaigns, module assignment, and dashboards.
- **Implicit deny governs functionality, not login.** A newly invited user auto-assigns the "Learner" role on invite acceptance, so they can log in and see assigned content immediately. Access to anything beyond Learner-level functionality still requires explicit role assignment by an admin.
- **Permission matrix is the ultimate goal, not the starting point.** Release 0 ships fixed predefined roles (Administrator, Content Manager, Learner). A fully custom, admin-authored permission matrix (arbitrary roles with per-action read-only/read-write/none) is deferred until there's a stable, multi-feature list of actions to build the matrix against — but every future release should keep this end state in mind when adding new gated actions.
- **Scoped API tokens are deferred**, not part of Release 0, since there are no real resources/scopes to gate yet. Design them once 2-3 real resource types exist (post Release 2).

## Release 0 — Foundation (skeleton)

Zero learning-content features. Establishes the permission/identity substrate everything else depends on.

- Email + password authentication.
- Opt-in, per-user 2FA (TOTP). *(A later release adds admin-level "enforce 2FA for all users" as an umbrella control.)*
- Fixed predefined roles: Administrator, Content Manager, Learner. Administrators manage role membership.
- Invite-based user creation (individual invites only — HRIS/Google Workspace import deferred to Release 8). Invite acceptance auto-assigns the "Learner" role.
- User Groups: basic CRUD, add/remove members, no nesting or dynamic/rule-based membership.
- Admin shell UI for managing users, groups, and role membership.

## Release 1 — Learning Modules (manual)

- Learning Module CRUD: create, edit, delete, import. No AI generation yet.
- Direct assignment of modules to individual users or groups (no campaigns yet — validates the assignment/targeting mechanism against the simplest content type).

## Release 2 — Campaigns & Grading

- Campaigns: collections of modules, targeted at users/groups. Reuses the assignment mechanism built in Release 1.
- Quiz/grading: modules can be configured to require a passing quiz score for completion.

## Release 3 — AI Chat Foundation

- Direct AI chat bot for general-topic conversations (the awareness use case from AGENTS.md point 5).
- Establishes the shared LLM provider layer (Claude Code / Ollama abstraction, streaming, conversation persistence) that later AI features reuse. Chosen as the first AI feature because it validates the provider abstraction with the lowest-risk output shape (free text, no structured extraction).

## Release 4 — AI Module Authoring

- Chatbot-driven module content generation and iterative regeneration, saving into the Release 1 module schema.
- Reuses the LLM layer from Release 3, now solving the harder problem of steering output into a structured, editable module draft.

## Release 5 — Dashboards

- Progress/completion dashboards for users, groups, and campaigns, built on the grading data produced in Release 2.
- AI-prompted dashboard creation, reusing the Release 3 LLM layer.

## Release 6 — RSS/News Nuggets

- Admin-configured RSS/news feed ingestion.
- LLM-generated information "nuggets" from ingested feeds, reusing the Release 3 LLM layer.

## Release 7 — Branding/Theming

- Per-deployment configurable colors, motifs, and logo, layered on top of the base theme (dark, light, color-blind-friendly; English and German).

## Release 8 — HRIS/Google Workspace Import

- Bulk user import integrations, extending the invite-based flow from Release 0.

## Deferred / cross-cutting, not yet scheduled

- Custom permission-matrix builder (arbitrary roles + per-action permission editing) — the end goal behind Release 0's fixed roles.
- Scoped API token generation/management.
- Admin-level "enforce 2FA for all users" toggle (umbrella control on top of Release 0's opt-in 2FA).
