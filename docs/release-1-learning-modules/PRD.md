Status: ready-for-agent

# Release 1 — Learning Modules (manual)

## Problem Statement

Release 0 built the identity substrate — accounts, sessions, roles, groups — but the platform still has nothing to teach anyone. There is no way to author a piece of learning content, no way to put it in front of a specific person or team, and no record of who has worked through what. The Content Manager role exists and is assignable, but it grants nothing beyond what a Learner already has, because there is no content for it to manage.

This release has to answer that without painting later releases into a corner. Three things make it harder than "add a CRUD screen":

1. **Compliance content is evidence.** A training platform's output is a defensible record that a named person read a specific text at a specific time. Content that can be silently edited underneath a completed record destroys that, so editing and versioning have to be designed together with completion, not bolted on when grading arrives in Release 2.
2. **Authored content is an attack surface aimed inward.** A Content Manager's content renders inside every Learner's authenticated session. This is the classic stored-XSS shape, and the content format chosen here determines whether that vulnerability class is filtered or eliminated.
3. **This schema is Release 4's output target.** AI-authored modules must save into whatever shape is defined now. A format an LLM cannot be constrained to produce means Release 4 either migrates every stored module or builds a conversion layer under deadline.

## Solution

Ship manually authored Learning Modules and direct assignment.

A module is metadata plus an ordered list of pages, each page a rich-text body stored as a validated ProseMirror document tree. Modules move through `draft ⇄ published → deleted`; editing a published module edits a draft copy, and each publish writes an immutable version snapshot, so no learner ever reads a half-finished edit and every completion record names the version it was made against.

Each module declares one language. EN and DE variants of the same material are linked in a translation group, and assignments target that group — so one assignment serves a mixed-language workforce, each learner getting their own language with a fallback to the group's primary variant.

Content Managers author, publish, import, export, and assign to groups. Administrators do all of that plus assign to named individuals. Learners see what has been assigned to them, plus any module an author has explicitly opted into an open catalog, work through it page by page, and complete it with an explicit attestation.

Every decision here is made so Release 2 (campaigns, quizzes) extends this rather than replaces it: assignment targets a translation group so campaigns can reuse the same targeting rows; completion is a timestamped, versioned, deliberate act so a quiz gate slots in immediately before it; content is structured JSON so Release 4's generation can be grammar-constrained into it.

## User Stories

### Authoring

1. As a Content Manager, I want to create a new learning module with a title, description, and language, so that I can start authoring content.
2. As a Content Manager, I want to add, edit, reorder, and delete pages within a module, so that I can structure the material into digestible steps.
3. As a Content Manager, I want to write page content in a visual editor with headings, emphasis, lists, links, quotes, and code blocks, so that I can produce readable material without knowing HTML or Markdown.
4. As a Content Manager, I want to insert images into a page, so that I can illustrate concepts visually.
5. As a Content Manager, I want to attach downloadable files to a module, so that learners can keep a reference copy of a policy or checklist.
6. As a Content Manager, I want to tag a module with free-text tags, so that it can be found and grouped later.
7. As a Content Manager, I want to set an estimated duration on a module, so that learners know what they are committing to before they start.
8. As a Content Manager, I want to save my work at any time without publishing it, so that I can author over several sittings.
9. As a Content Manager, I want to preview a module exactly as a learner will see it, so that I can check my work before publishing.
10. As a Content Manager, I want to publish a module, so that it becomes assignable and visible to its audience.
11. As a Content Manager, I want to edit an already-published module without learners seeing my work-in-progress, so that I can revise content safely while it is live.
12. As a Content Manager, I want to be told, when I publish a revision, whether to keep existing completions or require everyone to read it again, so that a typo fix does not drag the whole workforce back through the module and a policy change does.
13. As a Content Manager, I want to unpublish a module, so that I can take it out of circulation without destroying it or its history.
14. As a Content Manager, I want to delete a module, so that content that must not exist any more is genuinely gone.
15. As an Administrator, I want a deleted module's completion records to survive and be clearly tagged as deleted, so that our training evidence is not destroyed along with the content.
16. As a Content Manager, I want to see who created a module and who last edited it, so that I know whom to ask about it.
17. As a Content Manager, I want to be warned rather than silently overwrite someone else's changes if we edit the same draft at once, so that no one's work is lost.
18. As a Content Manager, I want to duplicate an existing module, so that I can base new material on something that already works.

### Translations

19. As a Content Manager, I want to declare which language a module is written in, so that it reaches the right learners.
20. As a Content Manager, I want to link the English and German versions of the same material as translations of one another, so that they are managed and assigned as one thing.
21. As a Content Manager, I want to nominate one variant as the primary, so that learners whose language has no variant still get something to read.
22. As a Content Manager, I want each language variant to be edited, versioned, and published independently, so that a correction to the German text does not force me to republish the English.
23. As a learner, I want an assigned module to open in my preferred language automatically, so that I can learn in the language I understand best.
24. As a learner whose language has no variant, I want to be shown the primary-language version rather than nothing, so that I can still complete my required training.

### Import and export

25. As a Content Manager, I want to export a module to a file, so that I can back it up or move it to another deployment.
26. As a Content Manager, I want to import a previously exported module file, so that content can be transferred between deployments without retyping it.
27. As a Content Manager, I want to import an existing Word document, PDF, or Markdown file as a module, so that our existing written material becomes usable training content without being rewritten from scratch.
28. As a Content Manager, I want imported content to arrive as an unpublished draft, so that I can review and correct the conversion before anyone sees it.
29. As a Content Manager, I want to be told what was dropped or changed during an import, so that I know where to look for conversion damage.

### Assignment

30. As a Content Manager, I want to assign a module to a user group, so that everyone in that team receives it.
31. As an Administrator, I want to assign a module to a named individual, so that I can target one person without creating a group for them.
32. As a Content Manager, I want someone who joins a targeted group later to receive the assignment automatically, so that new hires are not silently missed.
33. As a Content Manager, I want to set an optional due date on an assignment, so that there is a deadline to work toward and report against.
34. As a Content Manager, I want to mark an assignment as required or merely recommended, so that optional enrichment content does not get chased like mandatory compliance training.
35. As a Content Manager, I want to remove an assignment, so that content no longer relevant to a group stops appearing for them.
36. As a learner, I want to keep my completion record when I leave a targeted group, so that work I already did is not erased.
37. As a learner, I want an email when a module is assigned to me, in my own language, so that I find out without having to log in speculatively.
38. As a Content Manager, I want to see which groups a module is currently assigned to, so that I do not assign it twice.

### Reminders

39. As a learner, I want automatic email reminders as a due date approaches and after it passes, so that I do not miss required training.
40. As a Content Manager, I want to decide per assignment whether automatic reminders are sent, so that low-stakes recommended content does not nag people.
41. As an Administrator, I want to manually send a reminder to everyone still outstanding on a module, so that I can chase a deadline without waiting for the next scheduled run.
42. As a learner, I want a hard cap on how often the platform emails me about the same module, so that it does not become noise I filter away.
43. As an Administrator, I want to configure the timezone the platform uses to decide what "due today" means, so that reminders arrive at a sensible local hour.

### Learning

44. As a learner, I want a list of the modules assigned to me, showing due dates and what is overdue, so that I know what I have to do and by when.
45. As a learner, I want to see my progress through a module and resume where I left off, so that I do not have to redo pages or find my place manually.
46. As a learner, I want to move back and forward through a module's pages, so that I can re-read something before moving on.
47. As a learner, I want to confirm explicitly that I have read and understood a module once I have been through every page, so that my completion is something I asserted rather than something that happened to me.
48. As a learner, I want to see which modules I have already completed and when, so that I have my own record of my training.
49. As a learner, I want to re-open a module I have already completed, so that I can refresh my memory.
50. As a learner, I want to browse modules that were not assigned to me but that an author has opened to everyone, so that I can learn about a topic out of my own interest.
51. As a learner, I want modules that were never opened to everyone to be genuinely inaccessible to me, not merely hidden, so that implicit deny actually holds.
52. As a learner, I want to download a module's attachments, so that I can keep the reference material.
53. As a learner, I want the module viewer to work on my phone and to respect my chosen theme, so that I can do training wherever I am, comfortably.
54. As a learner using a keyboard or screen reader, I want to navigate a module fully without a mouse, so that the training is actually available to me.

### Finding content

55. As a Content Manager, I want to search modules by title and description and filter by tag, language, and status, so that I can find what I need among hundreds of them.
56. As a learner, I want to search and filter the open catalog, so that I can find content on a topic I care about.

### Reporting

57. As a Content Manager, I want to see how many people in each targeted group have completed a module, are in progress, have not started, or are overdue, so that I know whether my content is landing.
58. As a Content Manager, I want that view to show counts rather than names, so that authoring content does not require access to the staff directory.
59. As an Administrator, I want to see exactly who has and has not completed a module, so that I can answer "did everyone do the training?".
60. As an Administrator, I want to export a module's completion roster as CSV, so that I can hand it to an auditor.
61. As an Administrator, I want to see which version of a module each person completed, so that I can tell who has read the current text.

### Access control and accountability

62. As an Administrator, I want Content Managers to be able to author and assign content without gaining the ability to browse every user account, so that content authorship does not require directory access.
63. As a Learner, I want the authoring area to be entirely inaccessible to me, not just absent from my navigation, so that guessing a URL gains me nothing.
64. As an Administrator, I want module creation, editing, publishing, deletion, import, export, assignment, and reminders recorded in the audit log, so that there is an accountability trail for content and who was made to read it.
65. As a security reviewer, I want authored content to be incapable of executing script in another user's session, so that a compromised or malicious content author cannot pivot into other accounts.

## Implementation Decisions

### Content format — structured editor JSON

A page body is stored as a **ProseMirror document tree in a `jsonb` column**, not as HTML. This is the most consequential decision in the release and is backed by `docs/research/module-content-format-choice.md`, which should be read alongside this spec.

The short form of the rationale: storing HTML makes TrainDrain's entire defense against stored XSS the ongoing correctness of one dependency's HTML parser, on every write, forever. `bleach` is disqualified outright — its maintainers state there will be no future releases *including for security issues*. `nh3`/ammonia is a credible alternative and would be a defensible choice, but it has still shipped three mXSS/attribute-filtering advisories since 2025. Under JSON storage that bug class has nowhere to occur: no HTML string is stored, and nothing in the learner render path injects one. The residual risk narrows to `href`/`src` scheme validation — application code we own and can unit-test.

Two further reasons, in order: structured JSON is the only format the Claude API can grammar-constrain output into, which Release 4's AI authoring depends on; and Tiptap guarantees fully accurate content checking on JSON while explicitly declining to guarantee it on HTML, where marks "can be missed in certain situations" — silent formatting loss on save is a defect against the record itself on a compliance platform.

The research is equally clear about what this costs, and both costs are accepted here rather than wished away: Postgres full-text search over a JSONB tree pollutes the index with node type names and URL fragments, so a derived plain-text column is mandatory (see *Search*, below); and import requires one extra conversion hop.

**Editor and libraries.** Tiptap's core editor and StarterKit are MIT-licensed and cover the whole Release 1 authoring surface. `@tiptap/static-renderer` (MIT) renders the tree to React elements on the learner side. On the backend, `prosemirror-py` (BSD-3-Clause, pure Python) validates documents server-side without a Node sidecar. **Tiptap Conversion — the DOCX/PDF/ODT/EPUB import and export package — is a paid Pro product and must not be budgeted on**; the import paths below use free Python libraries instead.

**Schema.** One explicit ProseMirror schema is checked into the repo as the single source of truth, shared by editor and validator, with a `schema_version` integer stored on every document. Changing it requires its own migration ticket, because Tiptap silently drops content outside the schema. The Release 1 node set is deliberately small: `doc`, `paragraph`, `heading` (levels 2–4), `bulletList`, `orderedList`, `listItem`, `blockquote`, `codeBlock`, `horizontalRule`, `hardBreak`, `image`, `text`; marks `bold`, `italic`, `code`, `link`.

**Validation is server-side and non-negotiable.** Every incoming document is validated against that schema with `prosemirror-py` and **rejected with 422 on failure — never "sanitized and accepted."** Client-side editor configuration is UX, not a security control. In addition, enforced server-side on every write:

- A per-node attribute allowlist. Unknown attributes are a rejection, not a strip.
- Link `href` restricted to `https:`, `mailto:`, and site-relative paths. Image `src` restricted to the platform's own asset paths. `javascript:`, `data:`, `vbscript:` and anything else rejected. Tiptap's own `protocols`/`isAllowedUri` options are not relied on — their documentation makes no security claim.
- Caps on node count, nesting depth, and total serialized document size, so a document cannot be made unbounded.

**Rendering.** Learner-side rendering goes exclusively through `renderToReactElement` from `@tiptap/static-renderer/pm/react`. An **ESLint rule bans `dangerouslySetInnerHTML` across `src/frontend`**, so the guarantee is enforced by CI rather than by convention. A strict Content-Security-Policy ships with it — no `'unsafe-inline'` in `script-src`, and `img-src`/`style-src`/`connect-src` locked to the platform's own origins, since a strict `script-src` alone does not prevent exfiltration through `<img src>`.

### Data model

All tables use UUID primary keys and timezone-aware timestamps, matching Release 0's conventions.

- **`module_translation_groups`** — `id`, `primary_module_id`. Every module belongs to exactly one group; creating a standalone module auto-creates a group containing only it. This keeps assignment uniform: assignments always target a group, never a bare module, so adding a translation later never requires rewriting existing assignments.
- **`modules`** — `id`, `translation_group_id`, `language` (`en`|`de`), `title`, `description`, `estimated_duration_minutes`, `cover_asset_id`, `catalog_visible` (bool, default **false**), `status` (`draft`|`published`|`deleted`), `current_version_id`, `draft_revision` (int, optimistic-lock token), `created_by`, `last_edited_by`, `created_at`, `updated_at`, `deleted_at`. Unique on `(translation_group_id, language)` — one variant per language per group.
- **`module_pages`** — `id`, `module_id`, `position`, `title`, `body` (`jsonb`), `schema_version`, `search_text`, `search_tsv`. These rows are the **working draft**. Ordering is an integer `position` with a unique constraint on `(module_id, position)`, renumbered transactionally on reorder.
- **`module_versions`** — `id`, `module_id`, `version_number`, `published_at`, `published_by`, `revision_kind` (`minor`|`substantive`), `snapshot` (`jsonb`: the full page array plus title/description/language at publish time). Immutable once written. Learners always read the module's `current_version_id`; the snapshot exists so a completion record can name exactly what was read.
- **`tags`** / **`module_tags`** — free-text tags, normalized to lowercase on write and deduplicated.
- **`module_assets`** — `id`, `module_id`, `kind` (`image`|`attachment`), `s3_key`, `content_type`, `size_bytes`, `original_filename`, `uploaded_by`, `created_at`.
- **`assignments`** — `id`, `translation_group_id`, `target_type` (`user`|`group`), `target_id`, `due_date` (nullable), `requirement` (`mandatory`|`recommended`), `auto_reminders` (bool), `assigned_by`, `created_at`. **Membership is not expanded at assign time** — the target is stored, and a learner's module list is computed against their current group memberships at read time. This is what makes a later group joiner inherit the assignment automatically.
- **`module_progress`** — `id`, `user_id`, `translation_group_id`, `module_id` (the variant actually taken), `pages_viewed` (`jsonb` array of page ids), `current_page_id`, `started_at`, `completed_at`, `completed_version_number`, `superseded_at`, `created_at`, `updated_at`. Unique on `(user_id, translation_group_id)` — a learner has one progress record per body of material, regardless of which language variant they read. Deliberately **not** keyed on `assignment_id`, so progress survives an assignment being removed or the learner leaving a group; the assignment is looked up at read time.
- **`module_reminders`** — `assignment_id`, `user_id`, `kind`, `sent_at`. Exists so both the daily job and the manual nudge can enforce idempotency and the per-day cap.

### Lifecycle, versioning, and deletion

**States: `draft ⇄ published → deleted`.** `deleted` is terminal.

- Editing a published module edits its `module_pages` rows, which are the draft. Learners continue reading `current_version_id` until publish, so nobody ever sees a partial edit.
- **Publish** writes a new immutable `module_versions` row and repoints `current_version_id`. The publish action requires an explicit `revision_kind`:
  - `minor` — existing completions stand untouched.
  - `substantive` — every completed `module_progress` row for that translation group with a live assignment gets `superseded_at` set, so the learner sees it as outstanding again. **The prior completion is not erased**: `completed_at` and `completed_version_number` remain, so the record still shows that Anna completed v2 on a given date. The publish dialog states how many learners will be affected before confirming.
- **Unpublish** returns a published module to `draft`: it leaves the catalog, stops appearing in learners' lists, and cannot be newly assigned. Fully reversible; history untouched. This is the non-destructive retirement path.
- **Delete** is destructive and deliberate, modelled directly on Release 0's user-erase tombstone. It **removes all page content, all version snapshots, and all S3 assets**, and leaves a tombstone row retaining `title`, `language`, `version_number`s, and timestamps, so completion records still resolve and render as *"Phishing Awareness v2 — deleted"*. The module can never be assigned again, its assignments are removed, and progress rows are retained. The confirmation dialog states how many completion records the tombstone will carry.
- A learner mid-module when it is unpublished or deleted gets a clear "no longer available" state on their next request. Their progress row is retained.

**Concurrency.** Draft mutations carry the module's `draft_revision` token and are rejected with 409 if it has moved, so two Content Managers editing the same draft get a clear conflict rather than silent data loss. There is no module ownership — any Content Manager may edit, publish, or delete any module — but `created_by`, `last_edited_by`, and the audit log record who did what.

### Translations and language resolution

An assignment targets a `translation_group_id`. When a learner opens it, the variant is resolved as: **the published variant matching the learner's `preferred_language`; otherwise the group's published primary variant; otherwise any published variant.** The chosen variant is written to `module_progress.module_id`, so reports can show what was actually read.

A learner may switch language variant explicitly; `pages_viewed` is reset when they do, since the pages are different rows, but `started_at` and any prior completion are preserved. Each variant versions and publishes independently.

### Assignment and targeting

Assignment targets are users or groups. Content Manager assignment is **group-only**; individual targeting is Administrator-only. This is a deliberate data-minimization boundary: Content Managers see group names, descriptions, and member counts through a dedicated read-only endpoint, and never member lists or the user directory. The roadmap already names groups as the targeting unit, and a Content Manager may well be an external contractor writing content.

A learner's assigned list is the union of modules assigned directly to them and modules assigned to any group they currently belong to, deduplicated by translation group, with the nearest due date winning if two assignments cover the same material.

On assignment creation, every currently-targeted learner receives an email in their own `preferred_language`, reusing `app.security.mailer` (SES in production, LocalStack SES locally) exactly as invites and password resets do. Learners who join a targeted group later are not emailed retroactively — they simply see the module on their next visit.

### Reminders

Both a manual and a scheduled path ship, with a per-assignment `auto_reminders` toggle.

- **Manual nudge**: an Administrator can send a reminder to everyone outstanding on a module from the completion panel. Rate-limited to once per module per day and audit-logged.
- **Scheduled**: a daily job emails learners at **7 days before, 1 day before, on the due date, and weekly thereafter while overdue**, for `mandatory` assignments with `auto_reminders` enabled. A hard cap of **one email per learner per module per day** applies across both paths, enforced through `module_reminders`, which also makes the job idempotent if it runs twice.
- "Today" is evaluated in a deployment-wide timezone stored in the existing `system_settings` table (default `Europe/Berlin`), configurable by Administrators — the same pattern Release 0 established for invite expiry.

**Execution.** In production the job runs as an ECS task invoked by **EventBridge Scheduler**. Locally it runs as a separate `docker-compose` service invoking the same entrypoint on a fixed interval — EventBridge Scheduler is not in LocalStack Community, and the job's logic needs no AWS to be exercised. The entrypoint is identical in both, so the scheduled path is testable locally without emulating a scheduler.

### Media and assets

Images and downloadable attachments are stored in a **private S3 bucket** (LocalStack locally) with public access blocked and server-side encryption on. Keys are namespaced `modules/{module_id}/assets/{asset_id}`.

Assets are never served directly. A request goes to the API, which authorizes the caller against the module (assigned, catalog-visible, or an author/admin) and then redirects to a **presigned URL with a 5-minute TTL**. Object keys are opaque UUIDs and are never guessable from module content alone.

Upload hardening:

- Content type is **sniffed server-side**, never trusted from the client, and must match the declared kind.
- Images: `png`, `jpeg`, `webp`, `gif` only. **SVG is rejected outright** — it is a script-execution vector.
- Attachments: a conservative allowlist (`pdf`, `docx`, `xlsx`, `pptx`, `txt`, `csv`), served with `Content-Disposition: attachment` and a non-sniffable content type.
- Per-file and per-module total size caps, enforced before the object is persisted.
- Assets are served from an origin distinct from the application origin, so even a hypothetical content-type escape cannot execute against the app's origin.
- Deleting a module or an asset deletes the S3 object.

### Import and export

**Export** produces a self-contained `.zip`: a `module.json` carrying `format: "traindrain.module/1"`, the metadata, and the page trees, plus the referenced assets. This is the round-trip format for backup and for moving content between deployments.

**Import** accepts that native format plus DOCX, PDF, and Markdown, all converted into pages:

- Native `.zip` — validated against the export schema, then every page tree through the same server-side ProseMirror validator as authored content. No shortcut for "our own" format.
- **Markdown** — `markdown-it-py` on the `js-default` preset, which disables raw-HTML passthrough per its own security guidance. Pages split on H2; the leading H1 becomes the module title.
- **DOCX** — `python-docx` (free; Tiptap Conversion is not used), mapping headings, paragraphs, lists, and embedded images. Pages split on Heading 2.
- **PDF** — `pypdf` text extraction into paragraphs. Explicitly best-effort and lossy; the UI says so before the upload starts.
- Any HTML encountered on an import path is first sanitized with `nh3` on its **default allowlist** — never extending it with `svg`, `math`, `style`, `script`, `iframe`, `textarea`, or `title`, which is the precondition both recent ammonia advisories turn on — and then parsed to a node tree via `prosemirror-py`'s `from_html()`. `nh3` is kept as a dependency for this path only; it is not in the authoring write path.

Import hardening:

- Uploads **always land as unpublished drafts.** There is no import-and-publish path.
- Total size, zip entry count, and compression-ratio caps (zip-bomb defense); entry names rejected on path traversal.
- **No network fetches during import.** Remote image references are dropped rather than resolved — resolving them would be an SSRF sink reachable by anyone who can upload a file.
- The importing user is shown a conversion report listing what was dropped or altered.

### Search and discovery

Free-text tags plus search over title and description. Filters: language, status, tag.

Because the page body is a JSONB tree, `jsonb_to_tsvector` over it would index node type names (`doc`, `paragraph`, `link`) and URL fragments. Instead, `module_pages.search_text` is populated on write by walking the tree and concatenating text nodes, with `search_tsv` as a `GENERATED ALWAYS AS (to_tsvector(<config>, coalesce(search_text,'')))` stored column plus a GIN index. **The text-search configuration is chosen from the module's stored `language`** — `german` or `english` — not inferred at query time. Release 1 queries title and description; the page-level index is built now so full-content search is a query change later, not a migration.

### API surface

Atomic routers, one resource each, per AGENTS.md. All routes require an authenticated session; there is no anonymous access.

**Authoring** (`require_content_manager` — Content Manager or Administrator):

- `GET|POST /api/content/modules`, `GET|PATCH|DELETE /api/content/modules/{id}`
- `POST /api/content/modules/{id}/publish`, `POST /api/content/modules/{id}/unpublish`, `POST /api/content/modules/{id}/duplicate`
- `GET|POST /api/content/modules/{id}/pages`, `PATCH|DELETE /api/content/modules/{id}/pages/{page_id}`, `POST /api/content/modules/{id}/pages/reorder`
- `GET /api/content/modules/{id}/versions`
- `GET|POST /api/content/modules/{id}/assets`, `DELETE /api/content/modules/{id}/assets/{asset_id}`
- `POST /api/content/modules/import`, `GET /api/content/modules/{id}/export`
- `POST /api/content/translation-groups/{id}/variants`, `PATCH /api/content/translation-groups/{id}` (set primary)
- `GET /api/content/tags`
- `GET /api/content/groups` — group names, descriptions, and member **counts** only. This endpoint exists precisely so Content Managers never touch `/api/admin/groups/{id}/members`.

**Assignment**: `GET|POST /api/content/modules/{id}/assignments`, `DELETE /api/content/assignments/{id}`, `POST /api/content/modules/{id}/remind`. `target_type: "user"` is rejected with 403 for a non-Administrator; the manual nudge is Administrator-only.

**Reporting**: `GET /api/content/modules/{id}/report` — response shape differs by role, aggregate counts per targeted group for a Content Manager, full roster for an Administrator. `GET /api/content/modules/{id}/report.csv` — Administrator only.

**Learner**: `GET /api/me/modules`, `GET /api/me/modules/{translation_group_id}` (resolves the variant), `POST /api/me/modules/{translation_group_id}/pages/{page_id}/view`, `POST /api/me/modules/{translation_group_id}/complete`, `GET /api/catalog/modules`, `GET /api/modules/{id}/assets/{asset_id}`.

A new `require_content_manager` dependency joins `require_administrator` in `app/dependencies.py`. Every authorization decision is made server-side; the frontend gate is convenience only. IDOR is the specific risk to test here: a learner requesting a module they were never assigned, or an asset belonging to one, must get 403/404 regardless of how they reached the URL.

### Frontend

A new `/content` shell sits parallel to `/admin`, gated on Content Manager or Administrator. `/admin`'s existing Administrator-only gate is not touched — no Release 0 permission boundary moves in this release.

- `/modules` — the learner's assigned list, with due dates and overdue flags
- `/modules/browse` — the open catalog (only `catalog_visible` published modules)
- `/modules/{translation_group_id}` — the module viewer: page navigation, progress indicator, resume-where-you-left-off, and the attestation control on the final page, enabled only once every page has been viewed
- `/content` — module list with search and filters
- `/content/new`, `/content/import`, `/content/{id}` — authoring, with a preview mode
- `/content/{id}/assignments`, `/content/{id}/report`

Everything routes through `t()` for English and German, works against all three themes, and is responsive. The module viewer must be fully keyboard-navigable with correct focus management on page transitions — this is training content, and content people cannot reach is content that does not exist.

### Audit logging

Reusing Release 0's `audit_log` table and helper: `module_created`, `module_updated`, `module_published`, `module_unpublished`, `module_deleted`, `module_imported`, `module_exported`, `module_duplicated`, `assignment_created`, `assignment_removed`, `reminder_sent`. Each carries the acting user, the module or assignment, and a small JSON detail blob (for publishes: `version_number` and `revision_kind`; for substantive publishes: the count of superseded completions).

### Infrastructure

Terraform under `.deploy/dev`, extending Release 0's stack:

- A private S3 assets bucket — public access blocked, SSE enabled, versioning on, lifecycle rules for aborted multipart uploads — plus a scoped IAM policy for the backend task role.
- A CloudFront distribution or dedicated origin for asset delivery, separate from the application origin.
- An EventBridge Scheduler schedule plus the ECS task definition for the reminder job, with its own least-privilege task role.
- SES templates for the assignment and reminder emails, in both languages.
- `docker-compose` gains the interval-runner service for the reminder job. `docker-compose up` must still produce a fully working environment with no bespoke setup.

## Testing Decisions

Same two seams Release 0 established; no new seams are introduced.

**Backend — API level, against a real Postgres.** `pytest` + `pytest-asyncio` through the FastAPI HTTP interface, using the existing per-test-transaction fixtures. Areas specifically needing coverage:

- **Content validation is the security boundary**, so it gets adversarial tests, not happy-path ones: documents with unknown nodes, unknown attributes, `javascript:`/`data:`/`vbscript:` in `href` and `src`, over-deep nesting, over-large documents, and a `schema_version` mismatch — every one a 422, never a silent strip.
- Lifecycle: draft edits invisible to learners until publish; version snapshot written per publish and immutable thereafter; `minor` leaves completions alone; `substantive` supersedes them without erasing `completed_at`; unpublish reverses cleanly; delete tombstones correctly and leaves completion records resolvable.
- Language resolution: preferred language, fallback to primary, fallback to any; variant recorded on the progress row.
- Dynamic group targeting: a user added to a targeted group after assignment sees the module; a user removed from it loses the assignment but keeps their progress.
- Permission enforcement, tested from the denied direction as much as the allowed one: a Learner gets 403 on every `/api/content/*` route; a Content Manager gets 403 assigning to an individual user, and 403 on the per-person report and CSV; a learner gets 403/404 on a module and on an asset they were never assigned.
- Completion: the attestation is refused until every page is viewed.
- Optimistic locking: a stale `draft_revision` produces 409.
- Import hardening: zip bombs, path-traversal entry names, oversized uploads, and remote-image references dropped rather than fetched.
- Reminders: cadence boundaries, the one-per-learner-per-module-per-day cap, and idempotency when the job runs twice in a day.

**Frontend — Vitest + React Testing Library**, asserting rendered output and user-observable behavior, network mocked at the fetch boundary. Coverage: the module viewer's page navigation and resume behavior, the attestation control staying disabled until every page is seen, the authoring editor's save and publish flows including the minor/substantive choice, and the `/content` route being unreachable for a Learner.

Additionally: **a lint rule banning `dangerouslySetInnerHTML` in `src/frontend`, enforced in CI.** The XSS argument for JSON storage is only true as long as nothing reintroduces an HTML injection point, and that is a property worth machine-checking rather than reviewing for.

## Out of Scope

- **Quizzes, grading, and pass marks** — Release 2. Completion in Release 1 is the attestation only.
- **Campaigns** — Release 2. Release 1 ships direct assignment, which is the mechanism campaigns will reuse.
- **AI-generated or AI-edited module content** — Release 4. Release 1 only guarantees that the schema is a viable generation target.
- **SCORM and other packaged/opaque content** — moved to its own roadmap release (see *Further Notes*). No SCORM runtime, no sandboxed player, no `LMSSetValue` handling.
- **Video** — upload, transcoding, adaptive streaming, playback-position tracking, and the WebVTT captions that this project's accessibility posture would require. Its own release.
- **Progress dashboards and cross-module analytics** — Release 5. Release 1 ships per-module reporting only.
- **Certificates or completion PDFs.**
- **Module ownership, per-module ACLs, or an approval/review workflow** — any Content Manager may edit any module.
- **Full-text search across page bodies** — the index is built, the query is not.
- **Learner-facing comments, ratings, or discussion on modules.**
- **Scheduled publishing** (publish-at-a-future-date) and recurring/annual re-assignment.
- **Per-assignment reminder cadence customization** — the cadence is a platform constant in Release 1; only the on/off toggle is per assignment.
- **Nested or rule-based group membership** — still out, as in Release 0.
- **Scoped API tokens** — Release 1 brings the resource count to a point where these become designable, but they remain deferred.

## Further Notes

- **`docs/research/module-content-format-choice.md` is required reading before implementing the content model.** It records the sanitizer evidence, the Claude structured-output constraint (including that **recursive schemas are unsupported**, so Release 4's generation schema must be a deliberately depth-unrolled subset of the editor schema), the measured Postgres FTS behavior, and Tiptap's licensing boundary. Its "Follow-on obligations" section is a checklist, and the requirements in this spec are drawn from it.
- **ProseMirror's GitHub repositories were archived on 2026-04-01** and development moved to `code.haverbeke.berlin`. Dependency and advisory monitoring must point at the npm packages, not at GitHub, or upstream security fixes will go unnoticed. Track `nh3`/`ammonia` advisories via RustSec as well as PyPI, since the vulnerability record lives on the Rust side.
- **The roadmap changes as a result of this spec.** SCORM import was raised as a Release 1 requirement and moved out: it is not an import parser but a runtime — third-party HTML and JavaScript driving its own completion signal, which must be hosted on a separate origin because serving it same-origin would hand arbitrary uploaded script the session cookie. It also bypasses every model this release establishes (pages, versions, translation groups, attestation, AI authoring). `docs/ROADMAP.md` gains it as **Release 2.5 — Packaged Content (SCORM)**, after campaigns and grading. It is inserted as a decimal rather than renumbering, so existing references to Releases 3–8 in the Release 0 PRD and README stay accurate.
- **Markdown import was added** beyond what was selected. It costs almost nothing once DOCX/PDF conversion exists, and it is the format an LLM emits most reliably — which makes it useful groundwork for Release 4.
- **The Content Manager directory boundary is enforced in two places and both matter.** Group-only assignment is one; aggregate-only reporting is the other. Naming individuals in a completion report would hand a Content Manager the staff list through the back door, so the report's response shape differs by role rather than the UI merely hiding a column.
- **Release 2's quiz gate has a designated seam**: it belongs immediately before the attestation control, and `module_progress` already carries the version number a completion was made against, so a quiz result attaches to a specific version of specific content without schema change.
