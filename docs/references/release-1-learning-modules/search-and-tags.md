# Search, filters, and tags

Release 1, ticket 10. Finding things once there are hundreds of them — for
authors on the `/content` module list, and for learners on the open catalog.

## What changed

- `tags` and `module_tags` tables: a tag is a normalized (lowercase, deduped,
  ≤50 characters, ≤20 per module), free-text label on a module row — live
  metadata, not part of a version snapshot, so tagging a published module is
  findable immediately without a republish.
- `PATCH /api/content/modules/{id}` accepts an optional `tags` field: a full
  replacement of the module's tag set (`[]` clears it, leaving it out leaves
  it alone), normalized and deduplicated at the edge in
  `app.schemas.modules`. New tag rows are created with `ON CONFLICT DO
  NOTHING` (`app.search.get_or_create_tags`) so two authors typing the same
  brand-new tag at once produce one row, not a race.
- `GET /api/content/tags` lists every tag currently in use, for the
  authoring screen's autocomplete.
- `GET /api/content/modules` and `GET /api/catalog/modules` both gained `q`
  (title/description search), `language`, and `tags` (AND — a module has to
  carry every requested tag) query parameters, plus `status` on the
  authoring list only. `app.search` is the one place both routes build these
  filters from, so they can never disagree about what "matches" means.
  `q` is full-text search via `to_tsvector`/`plainto_tsquery`, with the
  search configuration (`german` or `english`) derived from each module's own
  stored `language` and never guessed from the query text — the same
  language-derivation logic `ModulePage.search_tsv` (ticket 2) uses. Unlike
  that column, this is computed at query time rather than stored in a
  generated, GIN-indexed column: title/description are short, unindexed scans
  over them are cheap at this scope, and adding that infrastructure for two
  columns is exactly the kind of thing ticket 2's own `search_tsv` exists to
  avoid needing later, if this ever needs to scale past a query-time scan.
  Full-content search over page bodies stays out of scope, as planned — this
  is title and description only.
- The catalog's filters are applied to each candidate module's live row (the
  same one `catalog_visible`/`status` are already checked on), not the
  frozen version snapshot a learner goes on to read — see the docstring on
  `list_catalog` in `app/routes/learning.py` for why that's an acceptable
  trade rather than a full-content-search-shaped problem.
- Frontend: a filter bar (search, language, status, tag) on
  `ContentModulesPage`, a tags field (comma-separated, with autocomplete) on
  `ModuleFormPage`, and a filter bar (search, language, tags) on
  `CatalogPage`, with both cards showing a module's tags. The free-text
  fields debounce (300ms) before re-querying, so typing doesn't fire a
  request per keystroke.
- Backend tests in `tests/test_search_and_tags.py`: tag normalization and
  dedup, the tag caps, the autocomplete list, German content matched via
  German stemming while identical English text is not, filters combining on
  both the authoring list and the catalog, and the catalog never returning a
  module that isn't `catalog_visible` and published.
