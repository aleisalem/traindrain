# Document import: Markdown, DOCX, PDF

Release 1, ticket 13. Existing written material becomes training content
without being retyped by hand: an author uploads a Word document, a PDF, or a
Markdown file and gets back a draft module, split into pages, ready to review
and correct. Conversion is lossy by nature, so every import returns a
conversion report naming what was dropped or altered, alongside the module it
created.

## What changed

- `POST /api/content/modules/document-import` (multipart: `file` plus a
  `language` field the author supplies, exactly as module creation already
  requires) converts the upload and returns `{module, conversion_report}`. It
  always lands as a fresh, unpublished draft in its own new translation group
  — there is no import-and-publish path, the same posture ticket 12's native
  import already established. `app/content/document_import.py` does the
  format-specific conversion work; `app/routes/document_import.py` is what
  makes the result trustworthy enough to store.
- **No code path here ever makes a network request.** A Markdown or DOCX
  image reference that points somewhere else — a URL, or a local path the
  uploaded file alone cannot resolve — is dropped and reported
  (`image_reference_dropped`), never fetched: resolving it would hand an SSRF
  sink to anyone who can upload a file. Only a DOCX's own **embedded** image
  bytes (already inside the uploaded file) become real, platform-hosted
  assets.
- **Every converted page goes through the exact same server-side ProseMirror
  validator** authored content does
  (`app.routes.content.validate_page_body`) — nothing about arriving from a
  converter earns a document a weaker check. Embedded DOCX images go through
  the exact same byte-level sniffing a fresh asset upload does
  (`app.content.uploads.sniff_upload`): SVG is refused, the extension has to
  agree with the sniffed type, and per-file/per-module size caps apply before
  anything is persisted, exactly as ticket 3 requires for a hand-uploaded
  image.
- **Markdown** (`markdown-it-py`, the `js-default` preset): raw HTML
  passthrough is disabled outright (`options["html"] = False`), not merely
  escaped — with it off, `markdown-it` never emits an `html_block`/
  `html_inline` token at all, so a literal `<script>` in the source becomes
  ordinary text automatically. An `nh3`-based sanitizer (default allowlist,
  never extended with `svg`/`math`/`style`/`script`/`iframe`/`textarea`/
  `title`) still exists as a second, independent layer for that node type on
  the chance a future `markdown-it` version or plugin reintroduces it —
  `nh3.clean`'s output is then parsed into real ProseMirror inline nodes
  (`<b>`/`<strong>`, `<i>`/`<em>`, `<code>`, and an `<a href>` that passes the
  same `https:`/`mailto:`/site-relative allowlist become the equivalent mark;
  everything else nh3's allowlist still permits contributes its text only),
  never reduced to inert plain text. `nh3` appears only on this import path,
  never on the authoring write path; since it is currently unreachable
  through the public endpoint, it is exercised directly in
  `tests/test_document_import.py` rather than through an end-to-end request.
  Pages split on `##`; the leading `#` becomes the module title (or the file
  name, if there is none). Headings outside the schema's levels 2–4 are
  clamped, reported as `heading_level_adjusted`. A link whose scheme isn't
  `https:`/`mailto:`/site-relative is kept as plain text rather than failing
  the whole import, reported as `link_dropped`.
- **DOCX** (`python-docx`): headings, paragraphs, bold/italic, hyperlinks,
  and bulleted/numbered lists (by style name, or by inspecting `numPr` for a
  generically-styled list, defaulting to bulleted when the numbering format
  can't be classified — reported once as `list_style_assumed_bullet`) map to
  the same schema. Pages split on `Heading 2`, mirroring Markdown's `##`.
  Tables have no equivalent node in the schema and are dropped outright
  (`table_dropped`). An embedded image is extracted from its run's
  `<w:drawing>`/`<a:blip>` and resolved via the paragraph's own package
  relationships — never a `src` value out of the document, which would be
  exactly the SSRF path this ticket refuses. `image` is a **block** node in
  the schema (it cannot nest inside a paragraph's inline content), so an
  image found mid-paragraph is placed as its own block immediately after it
  rather than inline — a documented position loss, not a dropped image.
  **A `.docx` is a zip archive wearing a different extension**, so it gets
  the same zip-bomb and path-traversal defenses ticket 12 built for a native
  `.zip` import (entry count, per-entry compression ratio, total uncompressed
  size — the same `import_max_entries`/`import_max_compression_ratio`/
  `import_max_uncompressed_bytes` settings — plus an entry-name check that
  refuses an absolute path or a `..`/`.` path segment) before `python-docx`
  ever opens it, and its `[Content_Types].xml` main-part declaration is
  checked so an Excel or PowerPoint file renamed `.docx` is refused as
  `unrecognised_format` rather than misread.
- **PDF** (`pypdf`): text-extraction only, explicitly best-effort — every PDF
  import's conversion report always carries a `pdf_best_effort` entry stating
  that layout, images, tables, and formatting are not preserved. Each source
  page becomes one module page (`Page N`), its text split into paragraphs on
  blank lines. An encrypted PDF is refused outright (`encrypted_pdf`) rather
  than silently producing an empty module.
- The upload's format is decided from its **bytes**, the same posture
  `app.content.uploads.sniff_upload` already takes for an asset: a `.docx`
  extension has to actually be a Word `.docx` (not any OOXML package, and not
  a PDF or plain-text file wearing the wrong extension), checked before
  anything is parsed.
- `module_document_imported` is audit-logged with the module id, the source
  format, the original filename, and the page/asset/issue counts.
- Backend tests in `tests/test_document_import.py` (21 tests): a Markdown
  happy path exercising every mapped node type; a remote image reference
  dropped and reported, with no asset row or byte of it ever stored; a
  Markdown file containing raw HTML/a `<script>` tag producing no node type
  outside the schema's own set; heading-level clamping; an unsupported link
  scheme kept as plain text; a DOCX happy path (headings, both list kinds,
  bold); a DOCX embedded image producing a real, platform-hosted asset; a
  DOCX table dropped and reported; a `.docx` zip bomb rejected by the real
  compression-ratio check (not a faked declared size); a `.docx` entry name
  attempting path traversal rejected; a spreadsheet renamed `.docx` rejected;
  a PDF happy path with the best-effort report entry; an encrypted PDF
  rejected; an unrecognised format rejected; a `.docx`-extension file whose
  bytes are actually a PDF rejected as an extension mismatch; a Learner gets
  403; the audit log entry; the `nh3`-based HTML sanitizer exercised directly
  (a `<script>` tag's content is dropped entirely, supported tags become the
  matching mark, an unsupported link scheme is dropped to plain text) since
  it is unreachable through the public endpoint with raw HTML disabled.

## What this ticket deliberately does not include

List nesting is flattened for DOCX (Markdown gets real nesting, since
`markdown-it`'s own tree already represents it); a DOCX list under a style
this converter cannot classify as bulleted or numbered is imported as
bulleted, once, rather than guessed per paragraph.

Ticket 13 itself shipped no frontend UI, matching ticket 12's own precedent —
the endpoint was API-only. A follow-up gave it a screen (below), reusing
the same `{module, conversion_report}` response.

## Frontend: `/content/import`

A Content Manager (or Administrator) reaches an "Import document" button on
`/content`, next to "New module". The screen (`DocumentImportPage.tsx`,
state in `useDocumentImport.ts`) is a single file picker plus the same
language choice module creation already asks for, a permanent notice that
PDF import is best-effort (shown before the upload starts, per the ticket's
own requirement), and a submit button disabled until a file is chosen.

On success, the screen shows the conversion report — each entry's server-written
`message` verbatim, since those sentences often name a specific dropped file
or count and are diagnostic content rather than static UI copy — and a button
to open the new draft at `/content/{id}` for review, rather than navigating
there automatically; the report is otherwise never seen. A handful of the
backend's rejection codes (`empty_file`, `unrecognised_format`/
`extension_mismatch`/`not_utf8`, `bad_document`, `encrypted_pdf`,
`empty_document`) get a localized (EN/DE) message; the size/structure caps
(`too_many_pages`, `too_many_entries`, `archive_too_large`,
`suspicious_compression_ratio`) fall back to the server's own message, the
same pattern `useModuleAssets`'s asset-upload error handling already uses for
a cap whose number can change server-side.
