# TrainDrain

A customizable e-learning and security-awareness platform. See [AGENTS.md](AGENTS.md) for the
full product vision and [docs/ROADMAP.md](docs/ROADMAP.md) for how it's being built out release
by release.

## Currently supported

Release 0 is in progress. So far:

- Local dev environment: Postgres, a FastAPI backend, LocalStack (S3 + SES emulation), and a
  prod-style static frontend build, all runnable via `docker-compose up`.
- Backend health-check endpoint (`GET /api/health`) with Alembic migrations wired to Postgres.
- Frontend i18n (English/German via react-i18next) and a Tailwind CSS-variable theme system
  (light, dark, colorblind-friendly) with a bold gradient-accented visual language — pill
  buttons/inputs, elevated cards, and a `Space Grotesk`/`Manrope` type pairing (see
  [docs/frontend-design-refresh.md](docs/frontend-design-refresh.md)).
- Core identity schema: `users`, `roles` (seeded with Administrator, Content Manager, Learner),
  `user_roles`, `sessions`, and `audit_log` tables, plus a bootstrap Administrator account seeded
  on first migration (its one-time random password is written to the backend's logs). Shared
  Argon2id password hashing and a password-policy validator (12-char minimum, HIBP breach check)
  live in `app.security` for reuse by the login/invite features that consume them next.
- Email+password login and logout, backed by server-side sessions (httpOnly/Secure/
  SameSite=Strict cookie; 12h absolute / 30min idle expiry) — `POST /api/auth/login`,
  `POST /api/auth/logout`, `GET /api/auth/me`. Repeated failed logins for an (email, ip) pair are
  sliding-window rate-limited. A user with `must_change_password` set (the bootstrap admin, on
  first login) gets a 403 from every endpoint but `/api/auth/logout` and
  `POST /api/auth/change-password` until they set a new password; changing your password
  invalidates your other active sessions. A minimal login / forced-password-change UI lives in
  `src/frontend/src/features/auth/`.
- An admin area (`/admin`), structurally separate from the learner-facing dashboard, with its own
  navigation — visible only to users holding the Administrator role. A stub admin-only endpoint
  (`GET /api/admin/ping`) enforces that role server-side (`require_administrator` in
  `app/dependencies.py`), so a Learner or Content Manager gets a 403 even navigating there
  directly, not just a hidden nav item. Frontend routing uses React Router
  (`src/frontend/src/App.tsx`, `src/frontend/src/features/admin/`).
- Admin-issued invites (`POST /api/admin/invites`, admin shell page at `/admin/invites`):
  single-use, hashed tokens emailed via SES/LocalStack-SES in the admin's chosen language, with
  optional role pre-assignment and an admin-configurable global expiry (`GET`/`PUT
  /api/admin/settings/invite-expiry-days`, default 7 days). Re-inviting an email invalidates its
  prior pending invite. `GET`/`POST /api/invites/{token}` (public — the invited user isn't a
  session yet) let a visitor check an invite and set their initial password, auto-assigning the
  Learner role plus anything the admin pre-assigned; an expired/used/superseded invite shows a
  clear "no longer valid" message. All invite issuance is audit-logged. Frontend:
  `src/frontend/src/features/admin/InviteUserPage.tsx` and
  `src/frontend/src/features/invites/AcceptInvitePage.tsx`.
- Forgot-password flow: `POST /api/auth/forgot-password` (email in, always 204 out — the
  response never leaks whether an account exists) emails a single-use, hashed, 1-hour-expiry
  reset token via SES/LocalStack-SES; a fresh request supersedes any still-pending one.
  `POST /api/auth/reset-password` validates the token, enforces the same password-policy
  validator, sets the new password, and invalidates all of that user's other active sessions.
  Frontend: `src/frontend/src/features/auth/ForgotPasswordPage.tsx` and
  `ResetPasswordPage.tsx`, reachable at `/forgot-password` and `/reset-password` without a
  session, plus a "Forgot your password?" link on the login form.
- Opt-in TOTP two-factor authentication: `POST /api/auth/2fa/enroll` generates a TOTP secret
  (envelope-encrypted with AES-256-GCM before storage, key from `TWO_FACTOR_ENCRYPTION_KEY`) and
  returns a QR code plus setup key; `POST /api/auth/2fa/enable` confirms it with a real TOTP code
  and returns ~10 Argon2id-hashed, single-use recovery codes shown once. Once enabled, a
  password-only `POST /api/auth/login` no longer issues a session — it sets a short-lived (5min),
  httpOnly `2FA challenge` cookie and returns `two_factor_required: true`; the real session is
  only issued by `POST /api/auth/2fa/verify` after a valid TOTP or recovery code (rate-limited the
  same way login is). `GET /api/auth/me` reports `two_factor_enabled`. A user can disable their
  own 2FA (`POST /api/auth/2fa/disable`, confirmed with their current password), and an
  Administrator can disable 2FA on a locked-out user's behalf after out-of-band identity
  verification (`POST /api/admin/users/2fa/disable`, audit-logged as `two_factor_admin_disabled`).
  Frontend: `src/frontend/src/features/auth/TwoFactorVerifyForm.tsx` (login-time second step),
  `src/frontend/src/features/twoFactor/TwoFactorSettings.tsx` (self-service enroll/disable flow on
  the dashboard), and `src/frontend/src/features/admin/AdminDisableTwoFactorPage.tsx`
  (`/admin/two-factor`, admin recovery UI).
- Admin user management: `GET /api/admin/users` lists every user with their roles and
  disabled/erased status. `POST /api/admin/users/{id}/disable` blocks an account's login and
  revokes its active sessions without deleting anything (reversible via
  `POST /api/admin/users/{id}/enable`); `POST /api/admin/users/{id}/erase` is the permanent,
  GDPR right-to-erasure action — it anonymizes the account's email and name (replacing the
  password with an unusable one and revoking sessions) while keeping a tombstone row so the audit
  log's foreign keys keep resolving. All three mutating actions are audit-logged; an admin can't
  disable or erase their own account. Frontend: `src/frontend/src/features/admin/AdminUsersPage.tsx`
  (`/admin/users`).
- Role assignment: `GET /api/admin/roles/{role_id}/members` lists who holds a role.
  `POST`/`DELETE /api/admin/users/{id}/roles/{role_id}` assign or remove a role from a user (404
  unknown user/role, 409 already-held/not-held; assigning to an erased account is also a
  conflict, removal isn't). Changing a user's roles revokes their other active sessions
  immediately — except when an admin changes their own roles, where the session performing the
  action is kept alive. All three actions are audit-logged. Frontend:
  `src/frontend/src/features/admin/AdminRolesPage.tsx` (`/admin/roles`), one card per role listing
  its members with assign/remove controls.
- User Groups: `GET`/`POST /api/admin/groups` list/create a group (name + description, 409 on a
  duplicate name); `PUT`/`DELETE /api/admin/groups/{id}` rename/redescribe or delete one (deleting
  cascades its membership rows). `GET /api/admin/groups/{id}/members` lists members;
  `POST`/`DELETE /api/admin/groups/{id}/members/{user_id}` add/remove one (404 unknown group/user,
  409 already-member/not-a-member; adding an erased user is also a conflict, removal isn't).
  Unlike roles, group membership changes don't revoke sessions — groups are for targeting future
  learning campaigns, not access control. Invite creation (`POST /api/admin/invites`) also accepts
  `group_ids` to pre-assign group membership, applied on acceptance alongside pre-assigned roles.
  All group CRUD and membership actions are audit-logged. Frontend:
  `src/frontend/src/features/admin/AdminGroupsPage.tsx` (`/admin/groups`).
- User profile self-service: `PATCH /api/profile/name` updates a user's own first/last name
  (email is immutable — the request schema forbids it, so trying to smuggle it in fails
  validation). `PATCH /api/profile/preferences` sets the user's language (EN/DE) and theme
  (light/dark/colorblind-friendly) preferences, persisted server-side on the user record so they
  follow the user across devices and sessions; `GET /api/auth/me` reports both. Changing your own
  password reuses the same `POST /api/auth/change-password` endpoint login already uses (ticket 2's
  policy validator, invalidates your other active sessions). A user with no stored theme
  preference gets an OS-based light/dark default the moment they log in — never the colorblind
  theme, which is always an explicit opt-in. Frontend:
  `src/frontend/src/features/profile/ProfilePage.tsx` (`/profile`, linked from the dashboard) —
  the app-wide theme/language application itself now lives in `src/frontend/src/App.tsx` rather
  than the dashboard, so it applies consistently across every authenticated screen.

Release 1 (learning modules) is in progress. So far:

- Module records and the `/content` authoring area: `GET`/`POST /api/content/modules` and
  `GET`/`PATCH /api/content/modules/{id}` create, list, read, and update a module's metadata
  (title, description, language, estimated duration). `created_by` and `last_edited_by` are set
  from the acting session and never accepted from the client — the request schemas forbid unknown
  fields, so trying to smuggle one in is a 422. A module's `language` is fixed at creation
  (a different language is a translation variant, not an edit), because the full-text search
  configuration its pages are indexed under is derived from it. Every module belongs to a
  translation group, and creating a standalone module auto-creates a group with that module as its
  primary, so assignment (which targets groups) never has to be rewritten when a translation is
  added later. `module_created` and `module_updated` are audit-logged. A new
  `require_content_manager` dependency admits Content Managers and Administrators; no Release 0
  boundary moved — a Content Manager still gets a 403 from every `/api/admin/*` route. Frontend:
  `src/frontend/src/features/content/` — a `/content` shell parallel to (not inside) `/admin`,
  with a module list (`/content`) and a create/edit metadata form (`/content/new`,
  `/content/{id}`), visible only to Content Managers and Administrators.

- Page authoring: an author adds pages to a module, writes each one in a Tiptap visual editor
  (headings, bold, italic, inline code, bullet and ordered lists, links, quotes, code blocks,
  dividers, line breaks), reorders and deletes pages, saves without publishing, and previews the
  module as a learner will see it. `GET`/`POST /api/content/modules/{id}/pages`,
  `PATCH`/`DELETE .../pages/{page_id}`, and `POST .../pages/reorder`. **Page bodies are stored as
  validated ProseMirror document trees in `jsonb`, never HTML.** One schema is checked into the repo
  and shared by the editor and the server-side validator; a document that doesn't conform is
  rejected with 422 and is never stripped-and-accepted. Nothing on the render path injects an HTML
  string — `dangerouslySetInnerHTML` is banned by a lint rule that fails the build and by a test,
  and a strict CSP ships in `nginx.conf`. Draft writes carry the module's `draft_revision` token, so
  a second author's save is a clear 409 rather than a lost edit. Full details in
  [docs/module-content-model.md](docs/module-content-model.md). Frontend:
  `src/frontend/src/features/content/ModulePagesPanel.tsx`, `PageEditor.tsx`, `PagePreview.tsx`.

- Concurrent-editing awareness: `POST /api/content/modules/{id}/editing` is a 15-second heartbeat
  that records the caller as having the module open and returns everyone else who does;
  `DELETE` on the same route frees the seat the moment they leave. The authoring screen shows those
  people as named avatars above the form, and saving the metadata while someone else is there opens
  a dialog naming them and stating that saving replaces their version — overwriting is **allowed**,
  it just never happens unannounced. Page bodies keep the stricter `draft_revision` conflict
  instead, because losing written material is not a recoverable annoyance. Frontend:
  `src/frontend/src/features/content/ModuleEditorsPresence.tsx`, `OverwriteWarningDialog.tsx`,
  `useModuleEditors.ts`.

- Module assets: an author inserts an image into a page from the editor's toolbar (picking one
  already uploaded, or uploading and inserting in one step) and attaches downloadable files to a
  module. `GET`/`POST /api/content/modules/{id}/assets` and `DELETE .../assets/{asset_id}` manage
  them; `GET /api/modules/{id}/assets/{asset_id}` **authorizes the caller against the module and
  then redirects (307) to a presigned URL with a 5-minute TTL** — assets are never served directly
  and the signed URL never appears in a response body. The bytes leave from an origin that is not
  the application's, which the CSP's `img-src` names via `ASSET_ORIGIN`. Uploads are treated as
  hostile: the content type is sniffed from the **bytes** (the client's declared type is never
  consulted) and the filename extension must agree with what was found; **SVG is rejected
  outright** as a script-execution vector; `docx`/`xlsx`/`pptx` are verified against the OOXML part
  declared inside the archive, which keeps macro-enabled formats out; per-file (5 MB image, 20 MB
  attachment) and per-module (100 MB) caps are enforced before anything is persisted. Deleting an
  asset deletes the stored object, and the UI says how many pages still embed it first —
  and, since publishing, how many **published versions** do, which is the heavier warning
  because a version snapshot is immutable and cannot be edited to remove the reference. Full
  details in [docs/module-assets.md](docs/module-assets.md). Frontend:
  `src/frontend/src/features/content/ModuleAssetsPanel.tsx` and `useModuleAssets.ts`.

- Publishing, version snapshots, unpublish, and duplicate: `POST /api/content/modules/{id}/publish`
  freezes the module's current pages (plus its title, description, and language) into an
  **immutable** `module_versions` row and repoints `modules.current_version_id` at it, so editing a
  published module edits the draft and nobody sees the work-in-progress until the next publish.
  Every publish requires an explicit `revision_kind` of `minor` or `substantive` — there is no
  default, so a request that omits it is a 422 and the publish dialog's two radios both start
  unchecked. **`substantive` is acted on, not just recorded**: it marks every completed learner
  of that translation group superseded *and* clears their page-view progress, so they have to
  read the new text before the attestation will accept them again — without that second half a
  learner could jump to the last page and re-confirm, since page ids survive an edit. Their
  previous `completed_at` and version number are kept; the completion is marked stale, never
  erased. `GET /api/content/modules/{id}/revision-impact` tells the author how many learners
  that is while they are still choosing, and the publish dialog shows it the moment
  `substantive` is selected. Version rows are immutable in the database, not just by convention: a `BEFORE UPDATE`
  trigger refuses any update to one. `POST .../unpublish` returns a published module to `draft`
  reversibly, keeping every page, version, and stored file (and leaving `current_version_id` in
  place, so an existing completion record still resolves); `POST .../duplicate` produces a fresh
  unpublished draft in its own new translation group, with its own copies of the pages and of the
  stored asset objects — the copied pages' `src` attributes are rewritten to the duplicate's own
  assets, so deleting the original can never blank out the copy. `GET .../versions` lists the
  history for authors. `module_published`, `module_unpublished`, and `module_duplicated` are
  audit-logged, publishes carrying `version_number`, `revision_kind`, and the count of
  completions the publish superseded. Full details in
  [docs/module-publishing.md](docs/module-publishing.md). Frontend:
  `src/frontend/src/features/content/ModulePublishPanel.tsx` and `PublishDialog.tsx`.

- The learner viewer: an author opts a published module into an open catalog
  (`catalog_visible`, default **false**, toggled from the publish panel), and a
  learner browses it at `/modules/browse`, opens a module at
  `/modules/{translation_group_id}`, and moves through its pages with a visible
  progress indicator, resuming where they left off. `GET /api/catalog/modules`,
  `GET /api/me/modules`, `GET /api/me/modules/{group_id}`,
  `POST .../pages/{page_id}/view`, and `POST .../complete`. Learners read the
  **published version snapshot, never the draft**, and material is addressed by
  translation group rather than module, so which language variant they get is
  resolved on open. A module an author never opened to everyone is genuinely
  inaccessible — `may_read_module` in `app/access.py` is the single decision
  point, asked both by the learner routes and by asset delivery, and anyone it
  refuses gets a 404 rather than a 403. The attestation on the final page is
  refused (409, and disabled in the UI) until every page has been viewed, and on
  success records `completed_at` and the version number that was read. A module
  withdrawn mid-read gives a clear "no longer available" state and **keeps** the
  learner's progress row. A module republished substantively comes back as
  outstanding — a banner in the viewer, a line on "my learning", and an
  "Updated" badge in place of "Completed" on the catalog card. The viewer moves focus to each new page's heading on
  transition and announces progress through a live region. Full details in
  [docs/learner-viewer.md](docs/learner-viewer.md). Frontend:
  `src/frontend/src/features/learning/`.

- Translations: a Content Manager links an already-authored, standalone module
  into another module's translation group as a new language variant
  (`POST /api/content/translation-groups/{id}/variants`, taking the existing
  module's id) and nominates which variant is primary
  (`PATCH /api/content/translation-groups/{id}`); `GET /api/content/translation-groups/{id}`
  lists a group's variants and its primary for the authoring screen. Linking is
  refused (409) if the source module already has translation siblings of its
  own, already has learner progress recorded against it, or would collide on
  language with an existing variant — each a clear conflict, never a silently
  merged duplicate. A learner opening a translation group is resolved to the
  published variant matching their `preferred_language`, falling back to the
  group's published primary, falling back to any published variant — and, once
  a learner has a progress row, that same resolution **stays fixed** to the
  variant they are already reading (their `pages_viewed` only means something
  within that text), overridable only by an explicit switch
  (`POST /api/me/modules/{translation_group_id}/language`), which resets
  `pages_viewed` while preserving `started_at` and any prior completion. Each
  variant is its own `modules` row with its own pages, versions, and
  `current_version_id`, so publishing one never touches another. Full details
  in [docs/translations.md](docs/translations.md). Frontend:
  `src/frontend/src/features/content/TranslationsPanel.tsx` (sibling list,
  "make primary", and linking another module in, shown on `/content/{id}`) and
  a language switcher in the learner viewer
  (`src/frontend/src/features/learning/ModuleViewerPage.tsx`), shown only when
  a translation group has more than one variant to read.

The rest of Release 1 — assignment, reminders, reporting — is still to come.

## Project structure

```
src/
  backend/         FastAPI app (Python, SQLAlchemy 2.0 async, Alembic)
    app/           Application code
      content/     ProseMirror schema (the checked-in source of truth), its server-side
                   validator, and the upload sniffer that decides what a file really is
      models/      SQLAlchemy models
      routes/      API endpoints (FastAPI routers)
      schemas/     Pydantic request/response models
      security/    Passwords, sessions, tokens, rate limiting, audit logging
      access.py    Who may read a module — one decision, asked by learners and by asset delivery
      storage.py   The private object store module assets live in (S3 / LocalStack S3)
      dependencies.py   Shared FastAPI dependencies (auth/session gates)
    alembic/       Database migrations
    tests/         pytest suite, run against a real Postgres instance
  frontend/        React + Vite SPA (TypeScript)
    src/
      features/auth/   Login / forced-password-change / forgot-, reset-password, and 2FA-verify UI, auth state hook
      features/admin/  Admin-only route tree (shell nav, overview, invite-a-user page, 2FA admin-disable page, user management page, role assignment page, groups page)
      features/content/  Content Manager authoring area (module list, metadata form, page editor,
                         preview, image/attachment panel, publish/version panel)
      content/         The checked-in ProseMirror schema and the Tiptap extension set built from it
      features/invites/  Public accept-invite page (set password, no session required)
      features/learning/  The learner's area (open catalog, "my learning", module viewer)
      features/twoFactor/  Self-service TOTP enroll/disable UI (QR code, recovery codes)
      features/profile/  Self-service profile page (name, password, language/theme preferences)
      i18n/        react-i18next config and en/de locale files
      styles/      Tailwind CSS-variable theme definitions (light/dark/colorblind)
      theme/       Theme-selection hook
docs/              Feature summaries and research notes
.scratch/          Working specs/tickets for the release currently in progress
```

## Running locally

Prerequisites: Docker and Docker Compose.

```bash
cp .env.example .env   # required — docker-compose needs POSTGRES_PASSWORD set
# Generate your own TWO_FACTOR_ENCRYPTION_KEY in .env (needed for 2FA to work):
python3 -c "import secrets, base64; print(base64.b64encode(secrets.token_bytes(32)).decode())"
docker-compose up
```

This starts:

- Postgres on `localhost:5433` (mapped off the default 5432 to avoid clashing with a host-installed
  Postgres; override with `POSTGRES_HOST_PORT` in `.env`)
- LocalStack (S3 for module assets, SES for mail) on `localhost:4566`. The backend creates the
  assets bucket on startup — with public access blocked and default encryption on — so no setup
  step is needed. Note that LocalStack Community does not *enforce* S3 request authorization, so
  the private-bucket property is real only in a deployment; see
  [docs/module-assets.md](docs/module-assets.md).
- The backend API on `localhost:8000` (runs Alembic migrations on startup, which seeds a
  bootstrap Administrator account — find its one-time password with
  `docker-compose logs backend | grep traindrain.bootstrap`)
- A prod-style static build of the frontend, served via nginx, on `localhost:8080`. Its
  `nginx.conf.template` is rendered at container start so the Content-Security-Policy's `img-src`
  can name `ASSET_ORIGIN` — the origin presigned asset URLs are served from, deliberately not the
  application's own.

For day-to-day frontend development with hot-module-reload, run the Vite dev server natively on
the host instead of relying on the containerized build:

```bash
cd src/frontend
npm install
npm run dev
```

The Vite dev server proxies `/api` requests to the backend at `localhost:8000`, so keep the
backend (and Postgres) running via `docker-compose up` (or `docker-compose up postgres backend
localstack`) while you work on the frontend.

## Running tests

Backend (requires a reachable Postgres — `docker-compose up postgres` is enough):

```bash
cd src/backend
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest   # defaults to postgresql+asyncpg://traindrain:traindrain@localhost:5433/traindrain;
         # override with DATABASE_URL if your Postgres differs. Also needs
         # TWO_FACTOR_ENCRYPTION_KEY set (any base64-encoded 32 bytes) — the
         # conftest.py fixtures default one in for local runs.
```

Tests run against a real Postgres database — the fixtures in `tests/conftest.py` apply Alembic
migrations once per test session and wrap each test in a transaction that's rolled back
afterwards, so tests can freely write data without polluting `docker-compose`'s dev database.

A handful of tests do assert on global state (for example, that exactly one `group_created` audit
entry exists), so they only pass against a database nothing has been clicked through by hand. If
you've been using the app locally, point `DATABASE_URL` at a database of its own rather than the
one `docker-compose` serves:

```bash
createdb -h localhost -p 5433 -U traindrain traindrain_test   # once
DATABASE_URL=postgresql+asyncpg://traindrain:traindrain@localhost:5433/traindrain_test pytest
```

The object store is faked in the suite (`FakeS3Client` in `conftest.py`), so no LocalStack is
needed to run the asset tests.

Frontend:

```bash
cd src/frontend
npm install
npm run test        # Vitest + React Testing Library
npm run lint        # oxlint — `react/no-danger` is an error, so a
                    # dangerouslySetInnerHTML anywhere in src/ fails the build
npx tsc -b          # typecheck
```

`npm run test` also asserts that the ProseMirror schema mirrored at
`src/frontend/src/content/prosemirrorSchema.json` is byte-identical to the backend's canonical copy
at `src/backend/app/content/prosemirror_schema.json`, and that the Tiptap editor can produce exactly
the nodes and marks that schema allows. If you change one, change both.

## Deploying to AWS

Not yet set up. Terraform under `.deploy/<environment>` and the ECS Fargate / S3+CloudFront
infrastructure described in the Release 0 spec (`.scratch/release-0-foundation/PRD.md`) land in a
later ticket.
