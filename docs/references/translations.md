# Translations: variants, primary nomination, language resolution

Release 1, ticket 6. The same material in English and German, managed as one
thing rather than two unrelated modules that happen to cover the same topic.

## What changed

- `POST /api/content/translation-groups/{id}/variants` — links an already
  existing, independently-authored, **standalone** module into this group as a
  new language variant. "Standalone" means the only module in its own
  translation group; linking anything else would orphan whatever it was
  already grouped with. Refused (409) if the source is already a variant of
  this group, is `deleted`, already has translation siblings of its own,
  already has learner progress recorded against its old group (moving it would
  strand that history), or would collide on language with an existing variant
  of the destination group. On success the source's own now-empty group is
  deleted.
- `PATCH /api/content/translation-groups/{id}` — nominates which variant is
  primary (`primary_module_id`).
- `GET /api/content/translation-groups/{id}` — a group's variants and its
  primary, for the authoring screen.
- `POST /api/me/modules/{translation_group_id}/language` — a learner's
  explicit choice of which text to read. Resets `pages_viewed` and
  `current_page_id` (pages are different rows in a different text);
  `started_at`, `completed_at`, and `completed_version_number` are untouched.
- `LearnerModule` gained `available_languages` — every language a learner may
  read, so the viewer only offers a switch when there is one to make.
- `translation_variant_linked` and `translation_primary_changed` audit
  entries.
- Frontend: `TranslationsPanel.tsx` (sibling list, "make primary", linking
  another module in) on the authoring screen, and a language switcher in
  `ModuleViewerPage.tsx`.

## Resolution is sticky, not re-decided every request

The learner-facing variant a translation group resolves to, in order: the
variant they are already reading (see below); otherwise their
`preferred_language`; otherwise the group's published primary, so somebody
whose language has no translation still gets the material rather than
nothing; otherwise any published variant, picked deterministically so two
requests agree.

The first branch is what makes an explicit switch (or a progress row) durable.
Without it, every open/view/complete call would re-resolve from scratch —
which was harmless before this ticket, when a group had at most one readable
variant, but would otherwise let a learner's `preferred_language` change (or
simply asking twice) pull them onto a different text mid-module than the one
their `pages_viewed` was collected against. `_pick_variant`'s
`sticky_module_id` parameter is that fix: once a `module_progress` row names a
module, that module wins as long as it is still published and readable — only
the explicit switch endpoint is allowed to move it. The open catalog applies
the same stickiness, so a learner's card never claims completion of a
different text than the one their history actually names.

## Each variant is independent

A variant is an ordinary `modules` row: its own pages, its own
`module_versions`, its own `current_version_id`, its own `draft_revision`.
Publishing the German variant repoints only its own `current_version_id` — the
English variant's is untouched. `module_progress` is what ties them together:
it is keyed on the *translation group*, not the module, so a learner has one
progress record per body of material however many language variants exist,
and `module_progress.module_id` names whichever one they actually read.
