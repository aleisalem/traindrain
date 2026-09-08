# Module content model

How a learning module's page content is stored, validated, and rendered. The reasoning behind the
format choice is in [research/module-content-format-choice.md](research/module-content-format-choice.md);
this document records what was actually built.

## The shape of it

A module is metadata plus an ordered list of pages. Each page has a title and a body, and the body
is a **ProseMirror document tree stored in a `jsonb` column — never HTML**.

```
modules ──< module_pages
              id, module_id, position, title,
              body jsonb, schema_version,
              search_config, search_text,
              search_tsv (generated, GIN-indexed)
```

`module_pages` rows are the **working draft**. Nothing here is visible to a learner; publishing
writes an immutable snapshot and arrives in a later ticket.

## One schema, two consumers

`src/backend/app/content/prosemirror_schema.json` is the single source of truth. It carries:

- `schemaVersion` — stamped onto every stored document
- `spec` — the ProseMirror node and mark specs
- `constraints` — heading levels, permitted link protocols, the image `src` pattern, and the
  ingest limits (node count, nesting depth, serialized size, pages per module)

The backend builds its `prosemirror-py` `Schema` from that file. The frontend has a mirrored copy at
`src/frontend/src/content/prosemirrorSchema.json` — the two Docker build contexts are separate, so
one file cannot literally be shared — and `src/frontend/src/content/schema.test.ts` fails if they
ever differ by a byte. The same test asserts that the Tiptap editor's node and mark sets match the
schema exactly, so the editor cannot produce a document the server would refuse.

The Release 1 node set: `doc`, `paragraph`, `heading` (levels 2–4), `bulletList`, `orderedList`,
`listItem`, `blockquote`, `codeBlock`, `horizontalRule`, `hardBreak`, `image`, `text`; marks `bold`,
`italic`, `code`, `link`. The `image` node exists but has nowhere to point until module assets land.

**Changing the schema is a migration, not an edit.** Tiptap silently drops content outside its
schema, so widening or narrowing the node set needs its own ticket that decides what happens to the
documents already stored under the previous `schema_version`.

## Validation: rejected, never sanitized

Every incoming body goes through `app/content/validation.py`, which **rejects with 422 and never
strips-and-accepts**. In order:

1. Serialized size cap.
2. A walk of the raw tree enforcing: known node and mark types; a per-node/per-mark **attribute
   allowlist** (an unknown attribute is a rejection — `prosemirror-py` on its own drops it and
   accepts the document, which is exactly the behaviour this refuses); only ProseMirror's own node
   keys; node count and nesting depth caps; attribute value constraints.
3. URL validation. Link `href` must be `https:`, `mailto:`, or a site-relative path — protocol-
   relative `//host` and `/\host` included in the refusal. Image `src` must match the platform's own
   asset-path pattern. Any URL carrying whitespace or a control character is refused rather than
   normalized, because browsers strip those before resolving and `\x01javascript:` navigates exactly
   as `javascript:` does.
4. `prosemirror-py` `Node.from_json(...).check()`, which enforces the content expressions — invalid
   nesting, a marked `codeBlock`, a `listItem` at the top level.

What gets stored is `node.to_json()`, the schema's canonical spelling of the document, not whatever
shape the client sent.

Tiptap's own `protocols`/`isAllowedUri` options are configured on the editor but are **not** the
control: anything can POST a document, and their documentation makes no security claim.

## Rendering

Learner-facing and preview rendering goes exclusively through `renderToReactElement` from
`@tiptap/static-renderer/pm/react`. No HTML string is produced on that path, so
`dangerouslySetInnerHTML` never appears. That is enforced twice rather than by convention:

- `react/no-danger` is an **error** in `.oxlintrc.json`, so `npm run lint` fails the build.
- `src/frontend/src/content/renderPath.test.ts` asserts the source tree is clean *and* shells out
  to the linter with a probe file to prove the rule would actually catch a new one.

A strict Content-Security-Policy ships in `src/frontend/nginx.conf` as the second line:
`script-src 'self'` with no `'unsafe-inline'`, and `img-src`/`connect-src` locked to `'self'`
(`data:` is allowed in `img-src` for the 2FA enrolment QR code). `style-src`/`font-src` allow
`fonts.googleapis.com`/`fonts.gstatic.com` for the webfonts in `index.html` — the only non-self
origins in the policy. Self-hosting those fonts would remove the exception, and would also stop
learner IP addresses reaching Google.

## Search

`search_text` is populated on every write by walking the tree and concatenating its `text` nodes.
`jsonb_to_tsvector` over the raw tree is **not** used: it indexes every node's type discriminator
(`doc`, `paragraph`, `link`) and every string attribute including URL fragments, so a learner
searching for "link" would match every page in the system.

`search_tsv` is a stored generated column over `search_text` with a GIN index. The text-search
configuration comes from the **module's stored `language`**, resolved at write time into the page's
`search_config` column, so German content is stemmed with German rules — never guessed from the
query text. A stored generated column must be `IMMUTABLE` and `text::regconfig` is not, so the
expression is a `CASE` over literal regconfigs (see `SEARCH_TSV_EXPRESSION` in
`app/models/module.py`).

Release 1 queries only title and description; the page-level index is built now so full-content
search is a query change later rather than a migration.

## Concurrency

There is no module ownership — any Content Manager may edit any module — so every draft mutation
carries the module's `draft_revision` token and is refused with **409** if it has moved. A
successful write advances the token and updates `last_edited_by`. A refused write advances nothing,
so a rejected document cannot lock a colleague out.

Page order is an integer `position` with a unique constraint on `(module_id, position)`, declared
`DEFERRABLE INITIALLY DEFERRED` so a reorder can renumber every row inside one transaction without
contorting the update order to dodge a transient collision. Deleting a page renumbers the rest, so
positions stay contiguous from 0.
