# Publishing: version snapshots, unpublish, duplicate

Release 1, ticket 4. An author publishes a module, and from that moment learners
read a frozen snapshot rather than the live draft.

## What changed

- `module_versions` table: `module_id`, `version_number`, `published_at`,
  `published_by`, `revision_kind` (`minor`|`substantive`), and `snapshot`
  (`jsonb`: the full page array plus title, description, language, and
  estimated duration at publish time). Unique on `(module_id, version_number)`.
- `modules.current_version_id` — the version learners read. `NULL` until the
  first publish.
- `POST /api/content/modules/{id}/publish` — writes the snapshot, repoints
  `current_version_id`, sets `status` to `published`.
- `POST /api/content/modules/{id}/unpublish` — back to `draft`, reversibly.
- `POST /api/content/modules/{id}/duplicate` — a new draft in its own new
  translation group, copying metadata, pages, and assets.
- `GET /api/content/modules/{id}/versions` — publish history for authors.
- `ModuleResponse` gained `current_version_number`.
- Frontend: `ModulePublishPanel.tsx` and `PublishDialog.tsx`, at the foot of the
  authoring screen.

## The four decisions worth knowing

### 1. `module_pages` is always the draft

Whatever a module's status, the pages an author edits are the draft. Learners
read the snapshot behind `current_version_id`, which is what lets somebody
revise a live module without anyone seeing a half-finished edit — and what lets
a completion record name the exact text that was read, which a pointer into
living page rows never could.

Page **ids** travel into the snapshot deliberately. Ticket 5 records which pages
a learner has viewed, and those ids have to keep meaning the same thing across
requests; a position in an array would not survive the author reordering the
draft underneath them.

### 2. Version rows are immutable in the database

A `BEFORE UPDATE` trigger on `module_versions` raises rather than allowing the
row to change. A version snapshot is the evidence of what somebody was made to
read, and evidence that can be quietly edited afterwards is not evidence — so
this is not left to every future route remembering not to touch it. `DELETE` is
deliberately still permitted: ticket 11's module delete purges a module's
snapshots along with its pages and its stored files, and that is the only thing
that ever removes one.

### 3. There is no default `revision_kind`

`PublishRequest.revision_kind` is a required `Literal["minor", "substantive"]`,
so a publish that does not answer the question is a 422; in the dialog, neither
radio starts checked and the confirming button stays disabled until one is. A
default would be the system deciding whether the whole workforce has to re-read
the material while appearing to ask.

The answer is acted on, not merely recorded. A `minor` publish leaves every
learner exactly where they are. A `substantive` one calls
`_send_learners_back`, which does two things to every `module_progress` row of
the module's translation group:

1. **Stamps `superseded_at` on completed rows.** `completed_at` and
   `completed_version_number` are deliberately left alone — the person did read
   v1 on that date, and a record that erased it would be lying about the past in
   order to describe the present. The learner sees the module as outstanding
   again, in the viewer, in "my learning", and on the catalog card.
2. **Empties `pages_viewed` and clears `current_page_id`** — for completed and
   part-read learners alike.

The second half is what makes the first mean anything, and it is the easy half
to leave out. A page keeps its id across an edit, so the page ids a learner
viewed in v1 still name every page of v2. Superseding a completion without
clearing that array re-opens the attestation while the "read every page first"
check is *already satisfied*: the learner walks to the last page, clicks
confirm, and has attested to material they have never seen. The array is the
evidence that check rests on, so a substantive rewrite has to invalidate it.
Part-read learners are reset for the same reason by a quieter route — pages read
in v1 must not count towards attesting to v2.

The scope is the whole translation group, because `module_progress` is keyed on
it: one learner, one body of material, however many language variants exist.

`GET /api/content/modules/{id}/revision-impact` returns
`{completed_learners, in_progress_learners}` for that group, which the publish
dialog shows the moment `substantive` is selected — and not before, since a
warning standing permanently beside the question is noise, and noise is how a
warning stops being read. It is a snapshot, not a promise: a learner may finish
the module between that call and the publish. The count that actually happened
goes into the `module_published` audit entry as `superseded_completions`.

The reset runs *after* `current_version_id` is repointed, which is what makes it
safe against a learner attesting at the same moment. `complete_module` takes a
row lock on the progress row, so that attestation either lands before the reset
(and is then superseded by it) or after it (and finds an emptied `pages_viewed`,
so the learner is asked to read the new text). Both orders end with the new
version unattested.

Once assignments exist (ticket 7), a substantive publish will still supersede
every learner of the group. An assignment decides who is *told* to read
something, not whose completion of it is still current.

### 4. Unpublish keeps `current_version_id`; duplicate keeps nothing shared

**Unpublish** changes `status` and nothing else. Every page, version, and stored
object stays, and `current_version_id` keeps pointing at the last published
version, so a completion record against it still resolves while the module is
out of circulation. Gating on `status` is what takes the module out of
circulation; ticket 5's catalog and ticket 7's assignment both read it.

Republishing is an ordinary publish, not a restore: it snapshots the draft as it
stands *now* and writes the next version, so an unpublish/republish round trip
with no edits does produce an identical v2 and does ask the minor/substantive
question again. That is the safe direction. Flipping the status back instead
would publish whatever had been written to the draft in the meantime under a
version number that predates it — silently shipping unreviewed text, which is
the exact failure the draft/snapshot split exists to prevent.

**Duplicate** goes the other way: the copy shares nothing with the original. Its
own translation group (a copy is new material, not a language variant), its own
page rows, its own asset rows, and its own copies of the stored objects — copied
server-side, so the bytes never travel through the application. The copied
pages' `src` **and `href`** attributes are rewritten to the duplicate's own
asset URLs, because pages left pointing at the original's assets would mean
deleting the original silently blanks out the copy and breaks its links. The
rewritten bodies go back through the same server-side ProseMirror validator, so
the invariant that everything in `module_pages` has been validated holds on this
path too, and what is stored is the validator's canonical document.

A copy that fails part-way takes its own objects back with it. The transaction's
rollback undoes the rows but cannot reach into the object store, so the already
copied objects are deleted by hand before the failure is re-raised — otherwise a
private bucket quietly accumulates files nothing can enumerate.

The copy's title comes from the client (defaulting to the original's) rather
than being suffixed server-side: "(copy)" is a word, and a platform that ships
in English and German has no business inventing one in a single language.

## What publishing changed about deleting an asset

Ticket 3's asset delete told the author how many *pages* still used a file. A
published version is a second referrer, and an immutable one: delete the page
from the draft, and the asset looks unused while the published snapshot still
embeds it — so deleting it would blow a hole in material learners are reading,
with no edit available to repair it.

`_reference_counts` in `routes/assets.py` therefore counts both, and
`AssetResponse` carries `referenced_by_versions` alongside `referenced_by_pages`.
The delete confirmation leads with the version count when there is one. Deleting
is still *allowed* — ticket 3's reasoning holds, content that has to go has to
be able to go — but it is no longer done in the dark.

Both counts match `src` and `href`, because a page can link an attachment as
well as embed an image: an asset URL is a site-relative path, which the schema
permits in a link, and the assets panel shows the author exactly that URL. The
duplicate path rewrites both for the same reason.

## What is deliberately not here

- **A `deleted` guard.** `deleted` is terminal and no route can set it yet;
  ticket 11 introduces the status and, with it, the refusal of every mutating
  route on a deleted module. A partial guard now would leave that ticket with
  half a check to find.
- **Scoping the supersede to an assignment.** There are no assignments yet
  (ticket 7). Every learner of the translation group is superseded, which is
  what that ticket will keep doing.
- **Telling a superseded learner by email.** Ticket 9's reminders are where a
  learner finds out without opening the platform; today the module reappears as
  outstanding the next time they look.
- **Publishing an empty module**, which is refused with a 409 (`empty_module`):
  a published module with nothing to read gives learners nothing, and would make
  ticket 5's "every page viewed" completion trivially true.
