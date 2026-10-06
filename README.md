# TrainDrain

A customizable e-learning and security-awareness platform. See [AGENTS.md](AGENTS.md) for the
full product vision and [docs/ROADMAP.md](docs/ROADMAP.md) for how it's being built out release
by release.

## Currently supported

Release 0 is in progress. So far:

- Local dev environment: Postgres, a FastAPI backend, LocalStack (S3 + SES emulation), and a
  prod-style static frontend build, all runnable via `docker-compose up`.
- Backend health-check endpoint (`GET /api/health`, used by infrastructure/monitoring — not
  shown anywhere in the UI) with Alembic migrations wired to Postgres.
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
  `src/frontend/src/features/profile/ProfilePage.tsx` (`/profile`, reachable from the profile
  control in the nav shell — see the unified navigation shell bullet below, which also merged
  two-factor settings and a navigation-placement preference onto this same page) — the app-wide
  theme/language application itself lives in `src/frontend/src/App.tsx`, so it applies
  consistently across every authenticated screen.

Release 1 (learning modules) is complete — all 14 tickets, per
[docs/release-1-learning-modules/tickets.md](docs/release-1-learning-modules/tickets.md):

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

- A single navigation shell (`AppShell`) replaced the three near-identical, role-scoped headers
  `/admin`, `/content`, and `/modules` used to render separately. Its nav shows the union of what
  a user's roles unlock — every authenticated user holds Learner, so "My learning"/"Browse
  catalog" are always there; "Content area" appears for Content Managers and Administrators;
  "Admin area" only for Administrators — and its placement (left sidebar or top bar) is a
  per-user preference (`PATCH /api/profile/preferences`, `nav_position: "left" | "top"`, default
  left), changed from the preferences page. A profile control (initials avatar, since there's no
  photo-upload feature yet) sits in the nav and opens `/profile`, now a single **Preferences**
  page combining name, password, language/theme, navigation placement, and two-factor
  authentication (previously split across the profile page and the old dashboard). Signing in
  lands a user on the highest-privilege area they hold — Administrator → Admin area, Content
  Manager → Content area, otherwise → My learning — rather than a shared placeholder dashboard,
  which is gone along with the backend-health-check button it used to show. Frontend:
  `src/frontend/src/shell/AppShell.tsx`, `navConfig.tsx`, `icons.tsx`.

- Assignment: a Content Manager assigns a module's material to a user group — an Administrator
  may additionally target a named individual — with an optional due date, a `mandatory` or
  `recommended` requirement, and an automatic-reminders toggle.
  `GET|POST /api/content/modules/{id}/assignments` and `DELETE /api/content/assignments/{id}`
  manage assignments, always against the module's *translation group* rather than one language
  variant, so a translation added later is automatically covered. **Membership is not expanded at
  assignment time** — the target (a group or a person) is stored, and a learner's list is computed
  against their *current* group memberships on every read, in `app.assignments`; a user added to a
  targeted group afterwards sees the module with no change to the assignment, and one removed from
  it loses the assignment but keeps whatever they already completed. This is also what makes an
  otherwise catalog-invisible module reachable at all: `may_read_module` (`app/access.py`) grew a
  second learner branch — assigned, directly or through a group — asked by the same one decision
  point the learner routes and asset delivery already shared. `target_type: "user"` is a 403 for a
  Content Manager, enforced both at creation and at removal; `GET /api/content/groups` gives a
  Content Manager group names, descriptions, and member **counts** only, so assigning content
  never requires touching `/api/admin/groups/{id}/members`, and an assignment's own read side never
  reveals an individual target's identity to anyone but an Administrator. Every currently-targeted
  learner is emailed once, at creation, in their own `preferred_language`, reusing
  `app.security.mailer`; a learner who joins the group later is not emailed retroactively.
  `GET /api/me/modules` now returns the union of what a learner has touched and what is assigned to
  them but not yet opened, deduplicated by translation group (the nearest due date wins when more
  than one assignment covers the same material), each row carrying its due date, its requirement,
  and a server-computed `overdue` flag (never true for a completed row). `assignment_created` and
  `assignment_removed` are audit-logged. Full details in
  [docs/assignment.md](docs/assignment.md). Frontend:
  `src/frontend/src/features/content/AssignmentsPanel.tsx` (shown on `/content/{id}`, the
  individual-target option gated on the caller holding the Administrator role) and
  `src/frontend/src/features/learning/MyLearningPage.tsx`, which now shows a not-started assigned
  module alongside started and completed ones, with its due date and an overdue flag.

- Reminders: a daily job chases mandatory, not-yet-completed training as its due date approaches
  and after it passes, and an Administrator can trigger the same nudge immediately instead of
  waiting for the next scheduled run. Only `mandatory` assignments with `auto_reminders` on and a
  due date set are ever reminded automatically — a `recommended` assignment or one with reminders
  turned off is never touched by either path. The cadence is 7 days before, 1 day before, on the
  due date, then weekly for as long as it stays overdue (`app.reminders.scheduled_kind_for_due_date`);
  a learner who has already completed the material (and is not superseded) is skipped. Every send —
  scheduled or manual — writes a `module_reminders` row, which is what makes a second run of the
  job on the same day a no-op and what the **one-email-per-learner-per-module-per-day cap** is
  checked against, joined across every assignment (a group one and an individual one can both name
  the same learner) that targets the module's translation group.
  `POST /api/content/modules/{id}/remind` is the manual nudge — Administrator-only, reaching the
  same audience the scheduled cadence would, and itself rate-limited to once per module per day
  (independently of the per-learner cap, and checked against its own `reminder_sent` audit entry
  rather than `module_reminders` — the entry is written even when the nudge reaches nobody, which a
  send-log check would miss) so a doubled click can't retrigger a second round of mail the moment
  the first lands; both paths are audited as `reminder_sent`. "Today" — for the cadence
  math and for the `overdue` flag on a learner's own list (`app.assignments.is_overdue`) — is
  evaluated in a deployment-wide timezone (default `Europe/Berlin`), readable and settable by
  Administrators through `GET|PUT /api/admin/settings/reminder-timezone`, the same pattern Release 0
  used for invite expiry. Reminder emails render in the recipient's `preferred_language`
  (`app.security.mailer.send_reminder_email`). The job itself
  (`app.reminders.run_scheduled_reminders`) is invoked by `python -m app.jobs.send_reminders` — the
  exact entrypoint production's scheduled task will call (ticket 14) — which `docker-compose`'s
  `reminder-runner` service loops locally (see "Running locally" below) to stand in for a scheduler
  without emulating one. Frontend: an Administrator-only "Remind everyone outstanding" button on
  `src/frontend/src/features/content/AssignmentsPanel.tsx`, reporting how many learners were
  actually reached (fewer than "everyone assigned" whenever the daily cap already covered some of
  them) or the day's rate limit if the module was already nudged today. Full details in
  [docs/reminders.md](docs/reminders.md).
- Reporting: `GET /api/content/modules/{id}/report` answers "did people do the training?" with a
  different shape depending on who asks — decided on the server, never by the UI. A Content
  Manager gets per-targeted-**group** counts (completed, in progress, not started, overdue) and
  never a name or email. An Administrator gets the full roster: every targeted learner's name,
  email, completion state, the version they completed, and their due date —
  `GET /api/content/modules/{id}/report.csv` exports that roster, Administrator-only. A completion
  a substantive republish superseded reports as outstanding (`in_progress`) rather than
  `completed`, but keeps its prior `completed_at` and version visible, so the roster still says
  what was read and when. Figures are counted across the whole translation group, the same scope
  `module_progress` and assignments are already keyed on. Frontend: a dedicated `/content/reports`
  page (`ModuleReportsPage.tsx`), reachable from its own "Reports" entry in the Content area nav —
  an author searches their modules by title or description (client-side, over the same module list
  `/content` already lists; server-side search is ticket 10's job) and picks one to read its
  report, rendered by `ModuleReportPanel.tsx` and `useModuleReport.ts` — unchanged components, just
  reached from the reports page instead of each module's own edit screen. A plain `<a href>` CSV
  download is offered only to an Administrator. Full details in
  [docs/references/module-reporting.md](docs/references/module-reporting.md).
- Search, filters, and tags: a Content Manager tags a module with free-text tags
  (normalized to lowercase and deduplicated) and searches/filters the `/content` module
  list by title, description, language, status, and tag, all combinable; a learner does the
  same over the open catalog. `GET /api/content/modules` and `GET /api/catalog/modules` share
  one place — `app.search` — that builds the `q`/`language`/`tags` filters, so the two routes
  can never disagree about what "matches" means; `status` is authoring-only, since a learner
  only ever sees published, catalog-visible material. Full-text search (`q`) is stemmed under
  each module's own stored `language` — German or English, never guessed from the query text —
  the same language-derivation logic ticket 2's page search uses, computed at query time rather
  than a stored, indexed column since title/description are short. `GET /api/content/tags` lists every tag in use
  for the authoring screen's autocomplete; `PATCH /api/content/modules/{id}` accepts a `tags`
  field as a full replacement of a module's tag set. Full-content search over page bodies stays
  out of scope, as planned. Frontend: a filter bar on `ContentModulesPage.tsx` and
  `CatalogPage.tsx` (debounced search, so typing doesn't fire a request per keystroke), and a
  tags field with autocomplete on `ModuleFormPage.tsx`. Full details in
  [docs/search-and-tags.md](docs/search-and-tags.md).
- Delete: a Content Manager permanently deletes a module — `DELETE
  /api/content/modules/{id}` — purging its draft pages, every published version snapshot, and
  every stored asset object (rows and S3 objects alike), and removing every assignment on its
  translation group. What is left is a tombstone: the `modules` row itself survives with its
  `title`, `language`, and timestamps intact and `status` set to `deleted`, modelled directly on
  Release 0's user-erase tombstone — `deleted_version_number` additionally captures the version
  `current_version_id` pointed at just before the delete cleared it, so even a module nobody ever
  completed still says what it was last published as, rather than only whichever learner's own
  `completed_version_number` happens to remember. `deleted` is terminal — `ensure_module_editable` in
  `app/access.py` is the one check every other mutating authoring route (metadata edits, page
  edits, publish, duplicate, translation linking, asset upload, assignment creation) asks before
  doing its own work, so a deleted module can never be resurrected through a side door.
  `GET /api/content/modules/{id}/deletion-impact` tells the confirmation dialog how many
  completion records the tombstone will carry before the delete happens, the same "tell the
  author the number first" shape ticket 4's `revision-impact` uses for a substantive publish.
  `module_progress` rows are never touched by a delete — they are the learner's own record, not
  the author's content — so a completed module keeps resolving and rendering under its
  tombstoned title in a learner's own "My learning" list, and, since assignments no longer name
  anyone once a module is gone, `full_roster`'s Administrator-facing report additionally reports
  anyone with a progress row on the material directly rather than only whoever a (now-deleted)
  assignment names, so "who did this training" stays answerable from an Administrator's report.
  A learner mid-module when it is deleted gets the same "no longer available" 404 an unpublished
  module already gives them (both fail the same `status != "published"` check), with their
  progress row retained. The default `GET /api/content/modules` list excludes `deleted` modules
  — there is deliberately no `status=deleted` filter value to browse them back into view; a
  tombstone is reached by the id a completion record or an audit entry already names.
  `module_deleted` is audit-logged with the affected completion count. Frontend: a "Delete
  module" control and `DeleteModuleDialog.tsx` confirmation on `ModulePublishPanel.tsx`, which
  also collapses to a plain deleted-state message (no publish/unpublish/duplicate/catalog
  controls) once a module's status is `deleted`. Full details in
  [docs/module-deletion.md](docs/module-deletion.md).
- Native export and import: `GET /api/content/modules/{id}/export` packages a module's draft —
  its metadata, its page trees in order, and its assets' actual bytes — into a self-contained
  `.zip` (a `module.json` manifest tagged `format: "traindrain.module/1"`, plus each asset at
  `assets/{asset_id}/{filename}`), for backup or for moving content between deployments.
  `POST /api/content/modules/import` accepts that archive and **always** creates a fresh,
  unpublished draft in its own new translation group — there is no import-and-publish path.
  Nothing about our own format is trusted more than an ordinary upload: every imported page tree
  goes through the exact same server-side ProseMirror validator authored content does (rejected,
  never stripped, on anything from an unknown node to a `javascript:` link), and every asset is
  re-sniffed from its actual bytes and re-checked against the same per-file and per-module size
  caps a fresh upload faces — the manifest's own claims about content type and size are
  informational only. Asset references inside a page body are rewritten to the new module's own
  assets, matched by asset id rather than by the module id in the URL, since a manifest carries no
  record of which module it used to live on. The archive itself is treated as hostile input:
  `app/content/transfer.py` checks entry count and per-entry compression ratio before decompressing
  anything, and additionally bounds every actual read against a shared byte budget that does not
  trust that metadata, so an entry that lies about its own size still cannot exceed it; every entry
  name is matched against a strict allowlist (`module.json`, or `assets/<uuid>/<basename>`) rather
  than checked for `..`, and there is no `extractall` anywhere, so a hostile name can never be
  written to disk under any name. `module_exported` and `module_imported` are audit-logged. Full
  details in [docs/module-transfer.md](docs/module-transfer.md).
- Document import: `POST /api/content/modules/document-import` (multipart: a file plus the
  author's chosen `language`) converts an uploaded Markdown, Word (`.docx`), or PDF file into a
  fresh, unpublished draft module, split into pages, alongside a conversion report naming what was
  dropped or altered — conversion is lossy by nature, so the author is told where to look for
  damage rather than losing it silently. **No code path here ever makes a network request**: a
  Markdown or DOCX image reference that points somewhere else is dropped and reported, never
  fetched, since resolving it would be an SSRF sink open to anyone who can upload a file — only a
  DOCX's own embedded image bytes become real, platform-hosted assets. Every converted page goes
  through the exact same server-side ProseMirror validator authored content does, and every
  embedded image through the exact same byte-level sniffing a fresh asset upload does — arriving
  from a converter earns a document no shortcut past either check. Markdown (`markdown-it-py`) has
  raw HTML passthrough disabled outright rather than merely escaped, with an `nh3`-based sanitizer
  (default allowlist only) as a second, independent layer that appears on no other path — its
  output is parsed into real bold/italic/code/link nodes rather than reduced to plain text; pages
  split on `##`, with the leading `#` becoming the module title. Word (`python-docx`) maps
  headings, paragraphs, bold/italic, hyperlinks, and bulleted/numbered lists the same way, splits
  pages on `Heading 2`, drops tables (no schema equivalent) with a report entry, and — since a
  `.docx` is a zip archive wearing a different extension — is checked against the same zip-bomb and
  path-traversal defenses (entry count, compression ratio, total size, entry naming) ticket 12's
  native import already built, before `python-docx` ever opens it. PDF (`pypdf`) is explicit
  best-effort text extraction only,
  always flagged as such in the report; an encrypted PDF is refused outright. `module_document_imported`
  is audit-logged. Frontend: an "Import document" entry point on `/content`, landing on
  `/content/import` (`DocumentImportPage.tsx`, `useDocumentImport.ts`) — a file picker, the same
  language choice module creation asks for, an always-shown notice that PDF import is best-effort
  (shown before the upload starts), and, on success, the conversion report plus a link to open the
  new draft for review. Full details in [docs/document-import.md](docs/document-import.md).

Release 2 (campaigns and grading) is in progress:

- Campaign drafts: a Content Manager builds a campaign — name, description, an ordered list of
  modules (each `mandatory` or `recommended`, referenced by translation group), group targets,
  optional start/due dates, and `auto_reminders`/`sequential` toggles — and saves it as a draft
  that no learner sees and that sends nothing. `GET|POST /api/content/campaigns` and
  `GET|PATCH /api/content/campaigns/{id}`; on `PATCH`, `modules` and `targets` are full
  replacements. A campaign is visible only to its creator — everyone else gets a 404, never a
  403 — and an individual target is a 403 for a Content Manager. A module that is unpublished or
  deleted is allowed in a draft but reported per module. `campaign_created` and `campaign_updated`
  are audit-logged. Frontend: `src/frontend/src/features/content/CampaignsPage.tsx` and
  `CampaignBuilderPage.tsx` (`/content/campaigns`), reordering by drag-and-drop or buttons. Full
  details in [docs/references/release-2-campaigns-grading/campaign-drafts.md](docs/references/release-2-campaigns-grading/campaign-drafts.md).

- Campaign collaborators and Administrator reach: a campaign's creator adds other Content Managers
  by email (`POST|DELETE /api/content/campaigns/{id}/collaborators`), who can then edit its
  metadata, modules and targets; only the creator or an Administrator manages collaborators or
  deletes a draft (`DELETE /api/content/campaigns/{id}`, draft only), and a collaborator attempting
  that gets a 403 while a non-participant still gets a 404. Administrators see and edit every
  campaign, are the only ones who can target named individuals, and can reassign the creator of an
  orphaned campaign (`POST .../owner`); collaborators survive an erased or demoted creator. A
  presence heartbeat (`POST|DELETE .../editing`) shows who else has a campaign open. All changes are
  audit-logged. Frontend: `CampaignCollaboratorsPanel.tsx` and the Administrator-only
  individual-target picker in `CampaignBuilderPage.tsx`. Full details in
  [docs/references/release-2-campaigns-grading/campaign-collaborators.md](docs/references/release-2-campaigns-grading/campaign-collaborators.md).

- Campaign activation and the learner's campaign view: `POST /api/content/campaigns/{id}/activate`
  and `.../close` move a campaign draft → active → closed (any other transition is a 409);
  activation is refused (422) unless every mandatory module is published and someone is targeted,
  and emails each currently-targeted learner once in their own language. `may_read_module` gained a
  campaign branch — a module is readable through an active campaign that targets the learner,
  derived live from current group membership (a closed campaign keeps only what was already
  started) — asked by both the learner routes and asset delivery. `GET /api/me/campaigns` returns
  each campaign with a live-computed "N of M required done" progress (a substantively republished
  module reopens it). The daily `python -m app.jobs.send_reminders` job also activates campaigns
  whose start date has arrived, idempotently. Frontend: `CampaignLifecyclePanel.tsx` in the
  builder and `CampaignCard.tsx` on "My learning". Full details in
  [docs/references/release-2-campaigns-grading/campaign-activation.md](docs/references/release-2-campaigns-grading/campaign-activation.md).

Release 1 infrastructure (ticket 14, closing out the release):

- Terraform under `.deploy/dev` for Release 1's own AWS footprint: the private module-assets S3
  bucket (public access blocked, SSE, versioning, lifecycle rules for aborted multipart uploads and
  expiring noncurrent versions) with a least-privilege IAM policy scoped to `modules/*` attached to
  the backend's existing task role; an EventBridge Scheduler schedule and ECS Fargate task
  definition for the reminder job, invoking the same `python -m app.jobs.send_reminders` entrypoint
  the local `reminder-runner` service loops, under its own least-privilege task role; and four SES
  templates for the assignment/reminder emails (EN/DE) — declared as infrastructure inventory, not
  yet called by `app.security.mailer`, which keeps rendering these in Python (see
  [docs/references/infrastructure.md](docs/references/infrastructure.md) for why). This stack takes
  Release 0's cluster, subnets, security groups, task roles, and secrets as input variables rather
  than creating them, since Release 0's own baseline stack does not exist in this repository yet —
  `terraform validate` runs clean standalone; `terraform plan`/`apply` need a real AWS account and
  Release 0's actual resource names. See [docs/references/infrastructure.md](docs/references/infrastructure.md)
  and [.deploy/dev/README.md](.deploy/dev/README.md).

## Project structure

```
src/
  backend/         FastAPI app (Python, SQLAlchemy 2.0 async, Alembic)
    app/           Application code
      content/     ProseMirror schema (the checked-in source of truth), its server-side
                   validator, the upload sniffer that decides what a file really is, and the
                   Markdown/DOCX/PDF converters behind document import
      models/      SQLAlchemy models
      routes/      API endpoints (FastAPI routers)
      schemas/     Pydantic request/response models
      security/    Passwords, sessions, tokens, rate limiting, audit logging
      access.py    Who may read a module — one decision, asked by learners and by asset delivery
      campaigns.py Campaign lifecycle (activate/close), live reach and completion, start-date activation
      assignments.py    Who a learner is assigned to read, resolved live against current group
                   membership — what `may_read_module` admits and what "my learning" lists
      reminders.py Scheduled cadence and manual-nudge logic shared by the daily job and the
                   Administrator's remind endpoint — the daily one-email-per-learner-per-module cap
      reporting.py Who is targeted and where they stand, walked once per group (Content Manager)
                   and once for the full roster (Administrator) — what the report endpoint and its
                   CSV export both read
      search.py    Language-aware title/description search and tag filtering, shared by the
                   authoring module list and the learner catalog so they can't disagree
      jobs/        Entrypoints invoked as scripts rather than through the API — `send_reminders.py`
                   is what `docker-compose`'s reminder-runner loops and production's scheduled task calls
      storage.py   The private object store module assets live in (S3 / LocalStack S3)
      dependencies.py   Shared FastAPI dependencies (auth/session gates)
    alembic/       Database migrations
    tests/         pytest suite, run against a real Postgres instance
  frontend/        React + Vite SPA (TypeScript)
    src/
      shell/       AppShell (the one nav+profile chrome every authenticated route renders inside), its per-role nav config, and its icon set
      features/auth/   Login / forced-password-change / forgot-, reset-password, and 2FA-verify UI, auth state hook
      features/admin/  Admin-only route tree (overview, invite-a-user page, 2FA admin-disable page, user management page, role assignment page, groups page)
      features/content/  Content Manager authoring area (module list, metadata form, page editor,
                         preview, image/attachment panel, publish/version panel, assignment panel,
                         a searchable per-module reports page, document import, campaign
                         list and builder)
      content/         The checked-in ProseMirror schema and the Tiptap extension set built from it
      features/invites/  Public accept-invite page (set password, no session required)
      features/learning/  The learner's area (open catalog, "my learning", module viewer)
      features/twoFactor/  Self-service TOTP enroll/disable UI (QR code, recovery codes), embedded in the Preferences page
      features/profile/  The Preferences page (name, password, language/theme/navigation-placement, two-factor authentication)
      i18n/        react-i18next config and en/de locale files
      styles/      Tailwind CSS-variable theme definitions (light/dark/colorblind)
      theme/       Theme- and nav-placement-selection hooks
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
- A `reminder-runner` service: the same backend image, looping `python -m app.jobs.send_reminders`
  hourly. That command is the exact entrypoint a production scheduled task invokes (ticket 14); the
  loop is only a local stand-in for that scheduler, and the job itself is idempotent, so a rerun
  within the same day sends nothing. To trigger it once by hand instead of waiting for the loop:
  ```bash
  docker-compose run --rm reminder-runner python -m app.jobs.send_reminders
  ```

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

Release 0's own baseline stack (the VPC, ECS Fargate cluster/ALB, and S3+CloudFront frontend
described in `docs/release-0-foundation/PRD.md`) is not yet set up in this repository.

Release 1's own additions are, under `.deploy/dev`: the private module-assets S3 bucket (public
access blocked, SSE, versioning, lifecycle rules), a least-privilege IAM policy for the backend's
assets access, the EventBridge Scheduler-triggered ECS task for the reminder job with its own task
role, and SES templates for assignment/reminder mail. It takes Release 0's cluster, subnets,
security groups, task roles, and secrets as input variables rather than creating them, so it can be
planned and reviewed independently of Release 0's own stack landing. `terraform validate` runs
clean with no AWS account; `terraform plan`/`apply` need one, plus Release 0's actual resource
names as variables. See [docs/references/infrastructure.md](docs/references/infrastructure.md)
for exactly what is and isn't stood up here, and [.deploy/dev/README.md](.deploy/dev/README.md)
for how to run it.
