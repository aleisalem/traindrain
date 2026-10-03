# Native export and import

Release 1, ticket 12. A module can leave one deployment and arrive intact in
another: an author exports a module to a self-contained `.zip` and imports
that file back — for backup, or to move content between deployments without
retyping it. Our own format gets no shortcut through either validator.

## What changed

- `GET /api/content/modules/{id}/export` builds a `.zip` in memory: a
  `module.json` manifest (`format: "traindrain.module/1"`, the module's
  title/description/language/estimated duration, its **draft** pages in
  order, and its assets' metadata) plus each asset's actual bytes at
  `assets/{asset_id}/{original_filename}`. It exports the draft, not a
  published version snapshot — the point of moving a module is to keep
  editing it on the other side. Not gated on the module's status: exporting a
  deleted module's tombstone is allowed and simply yields an archive with no
  pages and no assets, since a delete already purged both.
- `POST /api/content/modules/import` accepts that archive and always creates
  a **new**, unpublished draft in its own new translation group — there is no
  import-and-publish path, and nothing here writes to an existing module.
  Every page tree is validated through the exact same
  `app.routes.content.validate_page_body` an authored page goes through
  (schema conformance, size/depth/node caps, the `href`/`src` allowlists —
  rejected, never stripped), and every asset is re-sniffed from its actual
  bytes through the same `app.content.uploads.sniff_upload` a fresh upload
  goes through and re-checked against the same per-file and per-module size
  caps. The manifest's own claims about an asset's content type and size are
  informational only.
- Asset references inside a page body (`src`/`href`) are rewritten to the
  new module's own freshly-created assets, matched by the asset id at the end
  of the URL rather than by the module id in front of it — the manifest
  carries no record of which module a page used to belong to, only which
  asset it pointed at. The rewritten body is re-validated before it is
  stored, the same defense-in-depth ticket 4's duplicate uses.
- `app/content/transfer.py` treats the archive itself as hostile input, with
  **two independent** defenses against a zip bomb: the archive's declared
  metadata (entry count, per-entry compression ratio) is checked before any
  entry is decompressed, and every actual read is additionally bounded by a
  shared byte budget that does not trust that metadata — an entry whose real
  decompressed size disagrees with what it claims about itself still cannot
  exceed the budget. Every entry name is matched against a strict allowlist
  (`module.json`, or `assets/<uuid>/<basename>`) rather than pattern-checked
  for `..` — anything else, including a traversal attempt, is an
  "unexpected entry" rejection, and there is no `extractall` anywhere in this
  module, so a hostile name is never written to disk under any name at all.
  New settings: `import_max_archive_bytes`, `import_max_entries`,
  `import_max_compression_ratio`, `import_max_uncompressed_bytes`.
- The manifest and the archive's actual files have to agree exactly: every
  asset id the manifest declares must have exactly one corresponding
  `assets/<id>/...` entry, under the filename the manifest names for it, and
  every such entry in the archive must be declared — an orphan in either
  direction is rejected as `asset_mismatch`.
- A module may hold at most as many pages as `app.content.CONSTRAINTS`
  allows (the same cap `POST .../pages` enforces); an import that would
  exceed it is refused with 409, the same response shape and status a live
  page-create hitting the cap already gives.
- `module_exported` and `module_imported` are audit-logged with the module
  id, its title, and its page/asset counts.
- Two small shared helpers moved from single-use, underscore-prefixed
  functions to plain module exports so both the authoring routes and the
  transfer routes call the same code rather than a second copy of it:
  `app.routes.content.validate_page_body` and
  `app.routes.assets.read_upload_within_cap`.
- Backend tests in `tests/test_module_transfer.py`: a full export/import
  round trip preserves pages, their order, metadata, and an asset (bytes
  byte-identical, and its `src` reference rewritten to the new module's own
  asset rather than left pointing at the original's); an import always lands
  as `draft` even when the source was published; a zip bomb, a
  path-traversal entry name, an oversized archive, a page tree carrying a
  `javascript:` link, a stale `schema_version`, too many pages, a duplicate
  asset id in the manifest, an asset declared but missing from the archive,
  an undeclared asset entry, an SVG disguised as an image, an oversized
  asset, and assets that exceed the module quota are each rejected, with
  nothing left behind; a Learner gets 403 on both routes; an Administrator
  may also export and import.

## What this ticket deliberately does not include

There is no frontend UI for export/import in this ticket — its own checklist
in `docs/release-1-learning-modules/tickets.md` lists no frontend work, unlike
every sibling ticket in this release. Document import (Markdown/DOCX/PDF) is
ticket 13's job, built on top of this same "always lands as a draft, always
goes through the same validator" foundation.
