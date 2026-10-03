# The learner viewer: catalog, progress, and attestation

Release 1, ticket 5. The first point in the platform where somebody *reads*
something. An author opts a published module into an open catalog; a learner
browses it, opens a module, moves through its pages, leaves, comes back where
they were, and — once they have been through every page — confirms explicitly
that they have read and understood it.

## What a learner reads

**A version snapshot, never the draft.** `GET /api/me/modules/{translation_group_id}`
resolves a published variant and serves the pages out of the `module_versions`
row that `current_version_id` points at. An author revising a live module
changes nothing a learner sees until the next publish, which is also what lets a
completion record name exactly which text was read.

**Addressed by translation group, not by module.** A learner is reading a body
of material, not one particular text of it. Which variant they get is resolved
on open — their own language, else the group's primary, else any published
variant — so a group that gains a German translation later needs no link
anywhere to change. Ticket 6 extends that resolution with an explicit switch.

## Who may read it

One decision, in one function: `may_read_module` in `app/access.py` — a pure
predicate over a user and a module, asked by the learner routes and by the asset
delivery route, because a page and the image inside it have to be reachable by
exactly the same people.

- **Authors** (Content Manager, Administrator) may read any module. Previewing
  through the learner's own viewer is the only way to see what a learner gets.
- **Everyone else** may read a module only while it is *both* published *and*
  `catalog_visible`. That column defaults to **false**, so material reaches
  nobody until an author says it should — implicit deny as a property of the
  schema rather than a decision to remember.
- Ticket 7 adds the second learner branch here: the module is assigned to them,
  directly or through a group they currently belong to. That is a fact about the
  *user* — one query per request, not a lookup per module — so it belongs in a
  small audience value built once at the top of a request and asked per module,
  keeping this predicate pure. `app/access.py`'s docstring carries the shape.

A module nobody opened to the learner is a **404**, not a 403, and the same 404
(`{"code": "module_unavailable"}`) answers an unknown group, an unpublished one,
and one that was withdrawn while they were part-way through it. Which of those
it is would tell somebody who may not read a module that it is nonetheless
there.

## Progress

`module_progress` is unique on `(user_id, translation_group_id)`: one record per
learner per body of material, whatever language they read it in. It is
deliberately **not** keyed on an assignment — progress is something a person did,
and it survives an assignment being removed or the learner leaving the group it
was targeted at.

- **Opening a module writes nothing.** `GET /api/me/modules/{group_id}` is a
  read, and returns `progress: null` for a learner who has not read a page yet,
  so a stray click on the wrong catalog card leaves no trace on anybody's
  training history.
- `POST .../pages/{page_id}/view` is what starts the record, and what advances
  it: it marks a page as read and as where the learner is now. The row is
  inserted `ON CONFLICT DO NOTHING` and then read back under a row lock, so two
  tabs produce one row and one of them waits, rather than both appending to
  `pages_viewed` and one page quietly un-viewing itself. The page has to belong to the version being read; an id from
  anywhere else is a 404, because that array is what the attestation is checked
  against.
- `current_page_id` has **no foreign key** to `module_pages`, on purpose. The
  ids come from an immutable snapshot, and the draft page one of them names may
  have been deleted by an author since. A constraint would make a learner's
  bookmark something an author could break.
- A module withdrawn mid-read gives the learner a clear "no longer available"
  state on their next request. **The progress row is kept**, and the module stays
  on their own list marked as no longer openable.

## The attestation

`POST /api/me/modules/{translation_group_id}/complete` is refused with `409
pages_outstanding` until every page of the version being read has been viewed —
and the button is disabled client-side for the same reason, with the number of
pages still to read stated next to it. This is the one thing in the release a
learner asserts about themselves; an assertion that could be made without having
seen the material would be worth nothing to whoever later has to rely on it.

On success it stamps `completed_at` and `completed_version_number`, and clears
`superseded_at` — a completion of the current text is current by definition.
Re-attesting after a revision is allowed and updates the record, which is
exactly what a substantive republish asks a learner to do.

That republish is also what makes this check a real gate rather than a
formality. Page ids survive an edit, so a learner's viewed-page ids from v1
would otherwise satisfy every page of v2 — which is why a substantive publish
empties `pages_viewed` as well as marking the completion superseded. See
[module-publishing.md](module-publishing.md). The learner is told in three
places: a warning banner in the viewer, a line on "my learning", and an
"Updated" badge in place of "Completed" on the catalog card.

Release 2's quiz gate has its seam immediately above this control.

## Accessibility

This is training content: content people cannot reach is content that does not
exist. Two properties are deliberate rather than incidental.

- **Focus moves to the new page's heading on every transition** (and only on a
  transition — not on arrival, which would yank focus out of a document the
  learner just opened). A keyboard or screen-reader user ends up *at* the new
  page rather than parked on a button whose page was swapped out underneath
  them.
- **Progress is announced**, through a `role="progressbar"` with live values and
  an `aria-live` status naming the page position and title, so how far through
  you are is not a purely visual fact.

The viewer is responsive down to phone widths, renders in all three themes, and
routes every string through `t()` for English and German.

## Endpoints

| Endpoint | What it does |
| --- | --- |
| `GET /api/catalog/modules` | Published, catalog-visible material, one entry per translation group |
| `GET /api/me/modules` | What this learner has started and completed |
| `GET /api/me/modules/{group_id}` | Open a module: frozen pages, attachments, and where they were |
| `POST /api/me/modules/{group_id}/pages/{page_id}/view` | Record a page as read |
| `POST /api/me/modules/{group_id}/complete` | The attestation |
| `PATCH /api/content/modules/{id}` | Authors toggle `catalog_visible` from the publish panel |

A visibility toggle deliberately does **not** move `last_edited_by`: circulation
and authorship are different facts, and recording one as the other would put an
author's name against words they did not write. Every list a learner sees — the
catalog card, "my learning", and the viewer — takes its title from the published
snapshot, so a rename made to the draft since publication cannot make two
screens disagree about what the same material is called.
