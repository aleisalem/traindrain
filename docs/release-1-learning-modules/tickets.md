# Tickets: Release 1 — Learning Modules (manual)

Manually authored learning modules and direct assignment: a ProseMirror-backed authoring surface, immutable version snapshots, translation groups, group/individual assignment with reminders, a learner viewer ending in an explicit attestation, and per-module reporting. Source spec: `.scratch/release-1-learning-modules/PRD.md`. Required reading before ticket 2: `docs/research/module-content-format-choice.md`.

Work the **frontier**: any ticket whose blockers are all done. Tickets 6, 7, and 10 open in parallel once 5 lands.

## 1. Module records: content area, Content Manager gate, module CRUD

**What to build:** A Content Manager signs in and finds a `/content` area alongside (not inside) the existing `/admin` shell, where they can create a learning module with a title, description, language, and estimated duration, see every module in a list, edit its metadata, and see who created it and who last edited it. A Learner has no path in at all: no navigation entry, and a 403 from every content route even when the URL is typed directly. Modules exist only as drafts at this point — there is no page content, no publishing, and no delete.

Every module belongs to a translation group; creating a standalone module silently creates a group containing only it, so assignment never has to be rewritten when a translation is added later.

**Blocked by:** None — can start immediately.

- [x] Migrations create `module_translation_groups` and `modules` per the spec's data model, with UUID primary keys and timezone-aware timestamps matching Release 0's conventions, and a unique constraint on `(translation_group_id, language)`
- [x] `require_content_manager` joins `require_administrator` in the shared dependencies module and admits Content Managers and Administrators only
- [x] `GET|POST /api/content/modules` and `GET|PATCH /api/content/modules/{id}` create, list, read, and update module metadata; `created_by` and `last_edited_by` are set server-side, never accepted from the client
- [x] Creating a module with no translation group auto-creates one and makes the module its primary
- [x] `/content` shell renders a module list and a create/edit metadata form, routed through `t()` for EN/DE and working in all three themes, responsive
- [x] The `/content` navigation entry is visible only to Content Managers and Administrators
- [x] `module_created` and `module_updated` are written to Release 0's `audit_log` with the acting user and module
- [x] Backend tests: a Learner session gets 403 on every `/api/content/*` route; a Content Manager and an Administrator both succeed; a Content Manager cannot reach `/api/admin/*`, so no Release 0 boundary moved
- [x] Frontend test: `/content` is unreachable for a Learner
- [x] README's supported-features section updated

## 2. Page authoring: ProseMirror schema, server-side validation, editor and preview

**What to build:** A Content Manager writes the actual material. They add pages to a module, give each a title and a rich-text body written in a visual editor — headings, bold, italic, inline code, bullet and ordered lists, links, quotes, code blocks, horizontal rules, line breaks — reorder pages, delete pages, and save at any time without publishing. They can preview the module exactly as a learner will see it. Two Content Managers editing the same draft do not silently overwrite each other: the second save is refused with a clear conflict rather than a lost edit.

This is the release's security boundary. Page bodies are stored as validated ProseMirror document trees in `jsonb`, never HTML. One explicit schema is checked into the repo as the single source of truth shared by the editor and the server-side validator, and every document carries a `schema_version`. Documents that do not conform are **rejected, never sanitized and accepted**. Nothing on the render path — author preview or learner viewer — ever injects an HTML string, and CI enforces that rather than trusting review.

Images are deliberately out of this ticket; the `image` node is in the schema but has nowhere to point until ticket 3.

**Blocked by:** 1

- [x] One ProseMirror schema checked into the repo, consumed by both the Tiptap editor and the backend validator, covering exactly the Release 1 node set: `doc`, `paragraph`, `heading` (levels 2–4), `bulletList`, `orderedList`, `listItem`, `blockquote`, `codeBlock`, `horizontalRule`, `hardBreak`, `image`, `text`; marks `bold`, `italic`, `code`, `link`
- [x] Migration creates `module_pages` with `body jsonb`, `schema_version`, `search_text`, and `search_tsv` as a `GENERATED ALWAYS AS (to_tsvector(<config>, coalesce(search_text,'')))` stored column plus a GIN index; the configuration is chosen from the module's stored `language`, not inferred at query time
- [x] `search_text` is populated on every write by walking the tree and concatenating text nodes — `jsonb_to_tsvector` over the raw tree is not used
- [x] `GET|POST /api/content/modules/{id}/pages`, `PATCH|DELETE .../pages/{page_id}`, and `POST .../pages/reorder`; ordering is an integer `position` with a unique constraint on `(module_id, position)`, renumbered transactionally on reorder
- [x] Every incoming document is validated server-side with `prosemirror-py` against the checked-in schema and **rejected with 422 on failure** — no code path strips a node or attribute and accepts the document
- [x] Server-side per-node attribute allowlist: an unknown attribute is a rejection, not a strip
- [x] Link `href` restricted to `https:`, `mailto:`, and site-relative paths; image `src` restricted to the platform's own asset paths; Tiptap's own `protocols`/`isAllowedUri` options are not relied on as the control
- [x] Server-side caps on node count, nesting depth, and total serialized document size, enforced at ingest
- [x] Draft mutations carry the module's `draft_revision` token and are rejected with 409 when it has moved; a successful write advances it and updates `last_edited_by`
- [x] Tiptap editor in the authoring screen covers the full node set above, saves without publishing, and supports add / edit / reorder / delete of pages
- [x] Preview mode renders the module as a learner will see it, exclusively via `renderToReactElement` from `@tiptap/static-renderer/pm/react`
- [x] An ESLint rule bans `dangerouslySetInnerHTML` across `src/frontend` and fails CI — implemented as `react/no-danger: error` in **oxlint**, which is the linter this repo actually uses (there is no ESLint config); `npm run lint` exits non-zero on a violation, and a test shells out to the linter to prove the rule fires
- [x] A strict Content-Security-Policy ships: no `'unsafe-inline'` in `script-src`, with `img-src`, `style-src`, and `connect-src` locked to the platform's own origins — two documented exceptions: `img-src` also allows `data:` (the 2FA enrolment QR code is returned as a data URI), and `style-src`/`font-src` allow `fonts.googleapis.com`/`fonts.gstatic.com` for the webfonts already in `index.html`. Self-hosting those fonts would close both the CSP exception and the learner-IP-to-Google privacy exposure — worth its own small ticket
- [x] Adversarial backend tests, each asserting 422 and not a silent strip: unknown node type, unknown attribute, `javascript:` / `data:` / `vbscript:` in `href` and in `src`, over-deep nesting, over-large document, mismatched `schema_version`
- [x] Backend test: a stale `draft_revision` produces 409
- [x] Frontend tests: the editor's save flow, and page reorder reflected in the rendered order
- [x] README and a brief `docs/` summary of the content model updated

## 3. Module assets: images and downloadable attachments

**What to build:** A Content Manager illustrates a page by inserting an image, and attaches a downloadable reference file — a policy PDF, a checklist — to a module. Both land in a private object store and are never served directly: a request goes to the API, which authorizes the caller against the module and then redirects to a short-lived presigned URL. Keys are opaque UUIDs, so nothing about a module's content makes an asset guessable.

Uploads are treated as hostile. Content type is sniffed server-side and must match the declared kind; SVG is rejected outright as a script-execution vector; attachments come from a conservative allowlist and are served as attachments with a non-sniffable content type; per-file and per-module total caps are enforced before anything is persisted.

**Blocked by:** 2

- [x] Migration creates `module_assets` per the spec, with keys namespaced `modules/{module_id}/assets/{asset_id}`
- [x] `GET|POST /api/content/modules/{id}/assets` and `DELETE .../assets/{asset_id}`; deleting an asset deletes the underlying object. Upload is deliberately **not** a `draft_revision` mutation — it is additive, and bumping the token would 409 the author's own next page save, the very one that references the image
- [x] `GET /api/modules/{id}/assets/{asset_id}` authorizes the caller against the module and redirects (307) to a presigned URL with a 5-minute TTL; the signed URL only ever appears in a `Location` header, never a response body. `authorize_asset_access` is the single decision point — today authors only, and ticket 5's learner branches go there and nowhere else; anyone not admitted gets 404 rather than 403. The bucket has public access blocked and default encryption on, set on startup locally and by terraform in a deployment — but note LocalStack Community does not *enforce* S3 request auth, so that property is only real when deployed (documented in `docs/module-assets.md`)
- [x] `docker-compose`'s LocalStack service gains S3 alongside SES, and `docker-compose up` still produces a fully working environment with no bespoke setup — the backend creates the bucket on startup. Verified end to end against the real stack: upload → 307 → presigned URL on a different origin → byte-identical file back
- [x] Content type is sniffed server-side from the **bytes** and never trusted from the client; the filename extension must also agree with what was sniffed, so both the bytes and the name have to be honest rather than either alone
- [x] Images accept `png`, `jpeg`, `webp`, `gif` only; **SVG is rejected outright** — checked before either allowlist and for both kinds, so an SVG renamed `logo.png` is refused by name (`svg_not_allowed`) rather than falling out as "unrecognised"
- [x] Attachments accept `pdf`, `docx`, `xlsx`, `pptx`, `txt`, `csv` only, served with `Content-Disposition: attachment` (RFC 6266, both `filename` and `filename*`) and a non-sniffable content type — `application/octet-stream`, because S3 cannot emit an `X-Content-Type-Options` header on an object, so the type itself has to be the one that never renders; the true sniffed type stays on the row for the UI. Both are set on the object so they hold however it is fetched. OOXML is verified against the main part declared in `[Content_Types].xml`, which is what keeps **macro-enabled** formats out; `txt`/`csv` must decode as UTF-8, carry no control characters, and not begin with `<`
- [x] Per-file (5 MB image / 20 MB attachment) and per-module total (100 MB) caps are enforced before the object is persisted — nothing, row or object, is written until both pass. All three are settings. Note the limit of the in-handler check: Starlette parses the whole multipart body before the handler runs, so nginx's `client_max_body_size 25m` is what actually stops a hostile body reaching the application
- [x] Assets are served from an origin distinct from the application origin, and the CSP from ticket 2 is updated to match — `nginx.conf` became `nginx.conf.template`, rendered at container start so `img-src` can name `ASSET_ORIGIN` (LocalStack locally, the bucket's delivery origin deployed). An unset value leaves a token no browser recognises, so it fails closed to `'self'`
- [x] The editor can insert an uploaded image into a page body, producing an `image` node whose `src` passes ticket 2's allowlist; a module's attachments are listed on the authoring screen. There is deliberately **no** "image URL" field — anything typed in would be a document the server refuses, so the picker is the real thing rather than a simplification. One `useModuleAssets` hook owns the list, so the picker and the panel cannot disagree
- [x] Backend tests: an SVG upload is rejected (and one renamed `.png`, and one declared `image/png`); a file whose sniffed type contradicts its declared kind is rejected; an oversized file and an over-quota module are rejected, with nothing persisted in either place; the presigned URL's TTL comes from configuration; a Learner gets 404 on the asset endpoint and an anonymous caller 401; an asset id from another module is a 404 on both read and delete. 73 tests across `test_upload_sniffing.py` (the sniffer as a unit, including every rename) and `test_module_assets.py`
- [x] README updated, plus `docs/module-assets.md`

## 4. Publish, version snapshots, unpublish, duplicate

**What to build:** A Content Manager publishes a module, and from that moment learners read a frozen snapshot rather than the live draft. Editing a published module edits its draft; nobody sees the work-in-progress until the next publish. Each publish asks an unavoidable question — is this a typo fix or a policy change? — because that answer decides whether everyone has to read the material again. Unpublish takes a module out of circulation without destroying anything, reversibly. Duplicate gives an author a fresh draft based on material that already works.

Publishing writes an immutable version snapshot so that, later, a completion record can name exactly what was read. The `substantive` choice is recorded here; acting on it — dragging learners back through the module — arrives in ticket 7, where a live assignment exists to scope it.

**Blocked by:** 3

- [x] Migration creates `module_versions` (`version_number`, `published_at`, `published_by`, `revision_kind`, `snapshot jsonb` holding the full page array plus title, description, and language at publish time) and adds `current_version_id` to `modules`. Page **ids** are in the snapshot too, because ticket 5's progress rows key on them and a position in an array would not survive a reorder of the draft
- [x] `POST /api/content/modules/{id}/publish` requires an explicit `revision_kind` of `minor` or `substantive`, writes a new version row, and repoints `current_version_id`. Immutability is enforced by a `BEFORE UPDATE` trigger in the database rather than by every future route remembering not to touch the row — `DELETE` stays possible on purpose, because ticket 11's module delete has to purge snapshots. Publishing a module with no pages is a 409 (`empty_module`)
- [x] `POST /api/content/modules/{id}/unpublish` returns a published module to `draft`: it stops being assignable and leaves the catalog, fully reversibly, with history untouched. `current_version_id` deliberately keeps pointing at the last published version, so a completion record against it still resolves while the module is out of circulation. Republishing is an ordinary publish, not a restore — it snapshots the draft as it stands now, because flipping the status back would ship whatever had been written to the draft meanwhile under an older version number
- [x] `POST /api/content/modules/{id}/duplicate` produces a new unpublished draft copying metadata, pages, and assets, in its own new translation group. The stored objects are copied too and the copied pages' `src` **and `href`** attributes rewritten to the duplicate's own assets (a page can link an attachment as well as embed an image) — pages left pointing at the original's would mean deleting the original silently blanks out the copy — and the rewritten bodies go back through the same server-side validator
- [x] `GET /api/content/modules/{id}/versions` lists version history for authors — without the snapshots themselves, which would be pounds of payload for a line of text
- [x] The publish dialog forces the minor/substantive choice explicitly — there is no default that lets an author publish without deciding. Enforced on both sides: neither radio starts checked and the confirm button is disabled until one is, and `revision_kind` is a required Literal server-side, so a request that omits it is a 422
- [x] `module_published`, `module_unpublished`, and `module_duplicated` audit entries carry `version_number` and `revision_kind` where applicable
- [x] Backend tests: draft edits after a publish do not change the published snapshot; a second publish writes a second version and repoints `current_version_id`; a version row is immutable thereafter; unpublish reverses cleanly and republish works; a duplicate is an independent draft whose edits do not touch the original. 36 tests in `test_module_publishing.py`, including the duplicate's own asset objects, its rewritten `src` and `href` attributes, and the cleanup of already-copied objects when a copy fails part-way
- [x] Frontend test: the publish flow including the minor/substantive choice
- [x] README updated, plus `docs/module-publishing.md`

## 5. Learner module viewer: open catalog, page navigation, progress, attestation

**What to build:** The first time a learner gets to read anything. An author opts a published module into an open catalog; a learner browses that catalog, opens a module, and moves back and forward through its pages with a visible progress indicator. They can leave mid-module and come back to where they were. Once they have been through every page, and only then, they can confirm explicitly that they have read and understood it — a deliberate assertion, not something that happened to them. They can see what they have completed and when, and reopen a completed module to refresh their memory.

Modules an author never opened to everyone are genuinely inaccessible, not merely absent from a list. And because this is training content, the viewer has to actually work for everyone: full keyboard navigation with correct focus management on page transitions, on a phone, in the learner's chosen theme and language.

**Blocked by:** 4

- [x] Migration creates `module_progress` per the spec, unique on `(user_id, translation_group_id)` and deliberately **not** keyed on an assignment. `catalog_visible` needed no migration — it has been on `modules`, defaulting to false, since the table was created in ticket 1; implicit deny is a property of the column's default rather than something bolted on. `current_page_id` deliberately carries **no** foreign key: the ids come from an immutable snapshot, and a constraint would make a learner's bookmark something an author's delete could break
- [x] `GET /api/catalog/modules` lists only `catalog_visible` published modules, one entry per translation group; authors toggle catalog visibility from the publish panel (a `PATCH`, because it is metadata — publishing decides whether the material exists for learners at all, this decides whether they can find it unsent). The toggle deliberately does **not** move `last_edited_by`: circulation and authorship are different facts
- [x] `GET /api/me/modules/{translation_group_id}` resolves and returns the published variant with its pages, reading `current_version_id`'s snapshot rather than the draft — title and description come from the snapshot too (in the catalog and "my learning" as well, so no two screens can disagree about what the same material is called). It **writes nothing**: `progress` is null until the learner has actually read a page, so a stray click on the wrong card leaves no trace on their training history
- [x] `POST /api/me/modules/{translation_group_id}/pages/{page_id}/view` starts the progress record and advances it, recording a viewed page and the current page. Inserted `ON CONFLICT DO NOTHING` then read back `FOR UPDATE`, so two tabs produce one row rather than both appending to `pages_viewed` and one page quietly un-viewing itself. A page id from another module is a 404, since that array is what the attestation is checked against
- [x] `POST /api/me/modules/{translation_group_id}/complete` refuses with 409 `pages_outstanding` (carrying the counts, so the UI can say how many are left) until every page has been viewed, and on success stamps `completed_at` and `completed_version_number` and clears `superseded_at`
- [x] `GET /api/me/modules` returns what the learner has started and completed, with dates and version numbers; a completed module can be reopened
- [x] Viewer UI: page navigation forward and back, progress indicator, resume, attachment downloads, and the attestation control on the final page, enabled only once every page has been viewed. Rendering goes through the same `PagePreview` the author's preview uses, so the static renderer stays the only path a document takes to the screen
- [x] The viewer moves focus to the new page's heading on every transition — and only on a transition, never on arrival — announces the page position and the progress through a live region and a `progressbar`, is responsive down to phone widths, and routes every string through `t()`
- [x] A learner mid-module in a module that is unpublished gets a clear "no longer available" state on their next request, their progress row is retained, and the module stays on their own list marked as no longer openable
- [x] Access is one decision in one place — `may_read_module` in `app/access.py` — asked by the learner routes *and* by asset delivery, because a page and the image inside it have to be reachable by exactly the same people. Anyone it refuses gets a 404, and an unknown group, an unpublished one, and one never opened to the learner are deliberately the same 404
- [x] Backend tests: a learner requesting a module that is neither catalog-visible nor assigned gets 404 however they reached the URL — open, view, and complete — and likewise for its assets; the attestation is refused until every page is viewed; progress survives a session ending and resumes correctly. 27 tests in `test_learner_viewer.py`
- [x] Frontend tests: page navigation, focus on transition, resume behaviour, the attestation control staying disabled until every page has been seen, and the withdrawn-module state. 10 tests across `ModuleViewerPage.test.tsx` and `CatalogPage.test.tsx`
- [x] README updated, plus `docs/learner-viewer.md`

## 6. Translations: variants, primary nomination, language resolution

**What to build:** The same material in English and German, managed as one thing. A Content Manager links an EN and a DE module as translations of one another and nominates one as primary. Each variant is edited, versioned, and published independently, so fixing the German text does not force a republish of the English. A learner opening the material gets their own language automatically; a learner whose language has no variant gets the primary rather than nothing, so they can still complete required training. A learner may switch variant explicitly and keep their history.

**Blocked by:** 5

- [x] `POST /api/content/translation-groups/{id}/variants` adds a language variant to an existing group; `PATCH /api/content/translation-groups/{id}` sets the primary variant
- [x] The unique constraint on `(translation_group_id, language)` is enforced end to end — a second variant in the same language is a clear conflict, not a duplicate row
- [x] Variant resolution on open: the published variant matching the learner's `preferred_language`; otherwise the group's published primary; otherwise any published variant
- [x] The variant actually read is written to `module_progress.module_id`, so reports can show what was read
- [x] A learner can switch variant explicitly: `pages_viewed` resets because the pages are different rows, while `started_at` and any prior completion are preserved
- [x] Each variant publishes independently — publishing the German variant does not touch the English variant's `current_version_id`
- [x] Authoring UI shows a module's sibling variants, which is primary, and each variant's own status
- [x] Backend tests: all three resolution branches; the variant recorded on the progress row; a language switch resetting `pages_viewed` without erasing `started_at` or a prior completion; independent versioning of the two variants
- [x] README updated

## 7. Assignment: groups, individuals, due dates, emails, the learner's assigned list

**What to build:** Content reaches the people who have to read it. A Content Manager assigns a module to a user group, optionally with a due date, marked mandatory or merely recommended, with automatic reminders on or off. An Administrator can additionally target a named individual. Someone who joins a targeted group next month receives the assignment automatically, and someone who leaves keeps the completion they already earned. Targeted learners get an email in their own language so they find out without logging in speculatively. A learner sees a list of what they have to do and by when, with overdue clearly flagged.

A Content Manager can do all of this without ever seeing the staff directory: they see group names, descriptions, and member **counts**, and nothing else. That boundary is enforced server-side, not by hiding a column.

~~This ticket also makes `substantive` mean something~~ — **done ahead of this ticket.** A substantive republish already supersedes every completed learner of the translation group and clears everyone's page-view progress, so the attestation is a real gate on the new text rather than one click on the last page; the publish dialog states how many learners are affected, and the audit entry records the count. Scoping any of that to a *live assignment* is still this ticket's job, though the intended answer is that it stays group-wide: an assignment decides who is told to read something, not whose completion is still current. See `docs/module-publishing.md`.

**Blocked by:** 5

- [x] Migration creates `assignments` per the spec, targeting a `translation_group_id` and never a bare module (`superseded_at` handling on `module_progress` is already done — the column existed from ticket 5's migration and is now written)
- [x] **Membership is not expanded at assign time** — the target is stored, and a learner's list is computed against their current group memberships at read time
- [x] `GET|POST /api/content/modules/{id}/assignments` and `DELETE /api/content/assignments/{id}`; `GET` shows which groups a module is already assigned to
- [x] `target_type: "user"` is rejected with 403 for a non-Administrator
- [x] `GET /api/content/groups` returns group names, descriptions, and member **counts** only, so Content Managers never touch the admin member-list endpoints
- [x] On assignment creation, every currently-targeted learner is emailed in their own `preferred_language` through the existing mailer (SES in production, LocalStack SES locally), reusing the invite/password-reset pattern; learners who join a targeted group later are not emailed retroactively
- [x] `GET /api/me/modules` returns the union of directly-assigned and group-assigned material, deduplicated by translation group with the nearest due date winning, with due dates and overdue flags
- [x] A `substantive` publish sets `superseded_at` on every completed progress row for that translation group, **without erasing** `completed_at` or `completed_version_number`, and clears `pages_viewed` for every learner of the group so the material has to be read again rather than merely re-confirmed; the publish dialog states how many learners will be affected before confirming (`GET /api/content/modules/{id}/revision-impact`)
- [x] `assignment_created` and `assignment_removed` audit entries — ~~a substantive publish's audit detail carries the count of superseded completions~~ (done: `superseded_completions`)
- [x] Backend tests: a user added to a targeted group after assignment sees the module; a user removed from it loses the assignment but keeps their progress; a Content Manager gets 403 assigning to an individual; removing an assignment does not delete progress; a substantive republish supersedes without erasing the prior completion
- [x] Frontend tests: the assignment screen, and the learner's assigned list showing due dates and overdue state
- [x] README and a brief `docs/` summary updated

## 8. Reminders: scheduled job, manual nudge, per-day cap, timezone setting

**What to build:** Required training gets chased without becoming noise. A daily job emails learners as a due date approaches and after it passes, but only for mandatory assignments whose author left reminders on. An Administrator can also nudge everyone still outstanding on a module immediately, without waiting for the next scheduled run. Whatever the path, a learner is emailed at most once per module per day. "Due today" is decided in a deployment-wide timezone an Administrator can configure, so reminders arrive at a sensible local hour.

The job runs locally on the same entrypoint production will invoke, so the scheduled path is exercisable without emulating a scheduler.

**Blocked by:** 7

- [x] Migration creates `module_reminders` (`assignment_id`, `user_id`, `kind`, `sent_at`), which both paths consult for idempotency and the daily cap
- [x] Scheduled cadence: 7 days before, 1 day before, on the due date, and weekly thereafter while overdue — for `mandatory` assignments with `auto_reminders` enabled only
- [x] `POST /api/content/modules/{id}/remind` sends a reminder to everyone outstanding, is **Administrator-only**, is rate-limited to once per module per day, and is audit-logged as `reminder_sent`
- [x] A hard cap of one email per learner per module per day applies across both the scheduled and the manual path
- [x] The job is idempotent: running it twice in a day sends nothing the second time
- [x] "Today" is evaluated in a deployment-wide timezone stored in `system_settings` (default `Europe/Berlin`), readable and settable by Administrators through the same pattern Release 0 used for invite expiry — and `app.assignments.is_overdue` (My Learning's own overdue flag) reads the same setting, per its own docstring's instruction
- [x] Reminder emails render in the recipient's `preferred_language`
- [x] `docker-compose` gains an interval-runner service (`reminder-runner`) invoking the same entrypoint production will use, and `docker-compose up` still produces a fully working environment
- [x] Backend tests: each cadence boundary fires exactly once; the one-per-learner-per-module-per-day cap holds across both paths; a second run of the job in the same day is a no-op; a recommended assignment and an assignment with reminders off are never reminded; a non-Administrator gets 403 on the manual nudge. 17 tests in `test_reminders.py`
- [x] README updated with how to run the reminder job locally
- [x] Frontend: an Administrator-only "Remind everyone outstanding" button on the assignment panel (not in this ticket's original scope, but small enough to include alongside the endpoint it calls), with its own tests in `AssignmentsPanel.test.tsx`

## 9. Reporting: completion report and CSV roster

**What to build:** An author finds out whether their content is landing, and an Administrator can answer "did everyone do the training?" — but those are two different questions with two different answers. A Content Manager sees, per targeted group, how many people completed, are in progress, have not started, or are overdue, and never a name, because authoring content must not require directory access. An Administrator sees exactly who has and has not completed, which version each person completed, and can export the roster as CSV to hand to an auditor.

The response shape differs by role on the server. The UI is not what withholds the names.

**Blocked by:** 7

- [x] `GET /api/content/modules/{id}/report` returns aggregate counts per targeted group — completed, in progress, not started, overdue — for a Content Manager, and a full roster with per-person completion state for an Administrator
- [x] The Administrator roster shows which version number each person completed, so "who has read the current text" is answerable
- [x] `GET /api/content/modules/{id}/report.csv` is Administrator-only and exports the roster
- [x] Superseded completions are visible as outstanding while still showing the prior completion date and version
- [x] Report figures are computed across the whole translation group, so a mixed-language workforce reports as one population
- [x] Report UI on the authoring side, rendering both shapes, in both languages and all three themes
- [x] Backend tests: a Content Manager's response contains **no** user names or emails anywhere in the payload; a Content Manager gets 403 on the CSV route; the counts are correct across direct and group-derived assignment, including a learner who joined a targeted group after assignment
- [x] README updated

## 10. Search, filters, and tags

**What to build:** Finding things once there are hundreds of them. A Content Manager tags a module with free-text tags and searches the module list by title and description, filtering by language, status, and tag. A learner searches and filters the open catalog to find content on a topic they care about of their own accord.

Full-content search over page bodies stays out of scope — the index built in ticket 2 makes it a query change later rather than a migration.

**Blocked by:** 5

- [x] Migration creates `tags` and `module_tags`; tags are normalized to lowercase on write and deduplicated
- [x] `GET /api/content/tags` lists existing tags for autocomplete; authors add and remove tags on a module
- [x] Module list search covers title and description, with filters for language, status, and tag, combinable
- [x] The text-search configuration used for a query is derived from the module's stored `language` — `german` or `english` — never inferred from the query text
- [x] `GET /api/catalog/modules` gains the same search and tag/language filtering for learners
- [x] Search and filter UI on both the authoring list and the catalog, in both languages and all three themes
- [x] Backend tests: tag normalization and deduplication; German-language content matched with German stemming; filters combining correctly; the catalog search never returning a module that is not `catalog_visible` and published
- [x] README updated

## 11. Delete a module: tombstone, asset purge, records survive

**What to build:** Content that must not exist any more is genuinely gone — and the evidence that people were trained on it is not. Deleting a module destroys its page content, its version snapshots, and its stored files, and takes it out of circulation permanently. What remains is a tombstone carrying the title, language, version numbers, and dates, so a completion record still resolves and renders as *"Phishing Awareness v2 — deleted"* rather than a dangling reference. The confirmation states how many completion records the tombstone will carry, so nobody deletes a year of training evidence's context by accident.

This is modelled directly on Release 0's user-erase tombstone, and `deleted` is terminal.

**Blocked by:** 3, 5, 7

- [x] `DELETE /api/content/modules/{id}` sets status `deleted` and `deleted_at`, and removes all page rows, all version snapshots, and all stored asset objects
- [x] The tombstone retains `title`, `language`, version numbers, and timestamps; progress rows are retained; assignments for the module are removed
- [x] A deleted module can never be published, assigned, duplicated, or edited again — `deleted` is terminal, verified from the denied direction
- [x] The confirmation dialog states how many completion records the tombstone will carry before the action is taken
- [x] Completion records for a deleted module render with the tombstoned title and version in the learner's own history and in the Administrator report
- [x] A learner mid-module in a module that is deleted gets a clear "no longer available" state on their next request, with their progress row retained
- [x] `module_deleted` audit entry recording the module and the affected completion count
- [x] Backend tests: page rows, version rows, and stored objects are all gone after delete; completion records still resolve and render; every mutating route on a deleted module is refused; the deletion of assignments does not cascade into progress
- [x] README updated

## 12. Native export and import (`.zip` round-trip)

**What to build:** A module can leave one deployment and arrive intact in another. An author exports a module to a self-contained file carrying its metadata, its page trees, and its assets, and imports that file back — for backup, or to move content between deployments without retyping it. An import always arrives as an unpublished draft, so it is reviewed before anyone sees it.

Our own format gets no shortcut: every imported page tree goes through the same server-side validator as authored content, and the archive itself is treated as hostile input.

**Blocked by:** 3

- [x] `GET /api/content/modules/{id}/export` produces a `.zip` containing a `module.json` with `format: "traindrain.module/1"`, the metadata and page trees, plus the referenced assets
- [x] `POST /api/content/modules/import` accepts that archive, validates it against the export schema, and then validates **every page tree through the same server-side ProseMirror validator** ticket 2 built
- [x] Imports **always land as unpublished drafts** — there is no import-and-publish path
- [x] Total size, zip entry count, and compression-ratio caps are enforced (zip-bomb defense), and entry names are rejected on path traversal
- [x] Imported assets are re-keyed under the new module and re-checked against ticket 3's type sniffing and size caps
- [x] `module_exported` and `module_imported` audit entries
- [x] Backend tests: a full export/import round trip preserves pages, ordering, metadata, and assets; a zip bomb is rejected; a path-traversal entry name is rejected; an oversized archive is rejected; an archive containing a page tree with a `javascript:` link is rejected with 422 rather than imported and stripped
- [x] README updated

## 13. Document import: Markdown, DOCX, PDF, with a conversion report

**What to build:** Existing written material becomes training content without being rewritten. An author uploads a Word document, a PDF, or a Markdown file and gets back a draft module split into pages, ready to review and correct. Conversion is lossy by nature, so the author is told what was dropped or altered and knows where to look for damage — and is warned before the upload starts that PDF in particular is best-effort.

No import path is allowed to reach the network. Remote image references are dropped rather than resolved, because resolving them would hand an SSRF sink to anyone who can upload a file.

**Blocked by:** 12

- [x] Markdown import via `markdown-it-py` on the `js-default` preset, with raw-HTML passthrough disabled per its own security guidance; pages split on H2, with the leading H1 becoming the module title
- [x] DOCX import via `python-docx`, mapping headings, paragraphs, lists, and embedded images, splitting pages on Heading 2 — Tiptap Conversion (paid) is not used anywhere
- [x] PDF import via `pypdf` text extraction into paragraphs, with the UI stating it is best-effort and lossy **before** the upload starts — ~~UI~~ (this ticket ships no frontend, matching ticket 12's own precedent; every PDF import's conversion report always carries a `pdf_best_effort` entry, since that report is the only surface this ticket has)
- [x] Any HTML encountered on an import path is sanitized with `nh3` on its **default allowlist** — never extended with `svg`, `math`, `style`, `script`, `iframe`, `textarea`, or `title` — and then parsed to a node tree; `nh3` appears only on this path and never in the authoring write path
- [x] Every converted document is validated through the same server-side ProseMirror validator before it is stored
- [x] **No network fetches during import**: remote image references are dropped, not resolved
- [x] The importing user is shown a conversion report listing what was dropped or altered
- [x] Imports land as unpublished drafts, and the size, entry-count, and traversal caps from ticket 12 apply
- [x] Backend tests: a document with a remote image reference stores no remote content and reports the drop; a Markdown file containing raw HTML/script does not produce script-bearing nodes; a DOCX with embedded images produces platform-hosted assets; conversion reports list the dropped elements. 21 tests in `test_document_import.py`
- [x] README and a brief `docs/` summary of the import paths updated

## 14. Infrastructure: terraform, SES templates, scheduled reminder task

**What to build:** The release's AWS footprint, declared in terraform under `.deploy/dev`: the private assets bucket and its delivery origin, the scheduled reminder task, and the bilingual email templates. Release 1 additions only — the Release 0 baseline stack is assumed to arrive separately, and this ticket should state clearly in its own README section what it does and does not stand up.

**Blocked by:** 8

- [ ] Terraform under `.deploy/dev` for a private S3 assets bucket: public access blocked, SSE enabled, versioning on, lifecycle rules for aborted multipart uploads
- [ ] A scoped, least-privilege IAM policy for the backend task role covering exactly the assets bucket operations the API performs
- [ ] A CloudFront distribution or dedicated origin for asset delivery, separate from the application origin, matching the origin separation ticket 3 established locally
- [ ] An EventBridge Scheduler schedule plus the ECS task definition for the reminder job, with its own least-privilege task role, invoking the same entrypoint the local interval runner uses
- [ ] SES templates for the assignment and reminder emails in both English and German
- [ ] `eu-central-1`, per the project's data-residency posture; no secrets in the terraform — values come from the runtime environment or Secrets Manager
- [ ] `terraform validate` and `terraform plan` run clean against the module set
- [ ] README's deployment section updated to describe what this stack provisions and what it still depends on
