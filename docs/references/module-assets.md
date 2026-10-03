# Module assets: images and downloadable attachments

Release 1, ticket 3. An author illustrates a page with an image and attaches
downloadable reference files — a policy PDF, a checklist — to a module.

## What changed

- `module_assets` table: `kind` (`image`|`attachment`), `object_key`,
  `content_type`, `size_bytes`, `original_filename`, `uploaded_by`. Object keys
  are `modules/{module_id}/assets/{asset_id}`, both opaque UUIDs. (The PRD calls
  the column `s3_key`; it is `object_key` here because nothing in
  `app/storage.py` is S3-specific — the same code runs against LocalStack — and
  a column named after one vendor would be wrong the first time that changes.)
- `GET|POST /api/content/modules/{id}/assets` and
  `DELETE .../assets/{asset_id}` — authoring, Content Managers and
  Administrators.
- `GET /api/modules/{id}/assets/{asset_id}` — delivery. Authorizes, then
  redirects (307) to a presigned URL.
- `app/content/uploads.py` — the upload sniffer.
- `app/storage.py` — the object store, S3 in a deployment and LocalStack's S3
  locally.
- Frontend: `ModuleAssetsPanel.tsx`, `useModuleAssets.ts`, and an image picker
  in the page editor's toolbar.

## The three decisions worth knowing

### 1. Assets are never served directly

A request goes to the API, which authorizes the caller against the **module**
and only then mints a presigned URL with a 5-minute TTL. The signed URL only
ever appears in a `Location` header — never in a JSON body, where it would
outlive the check that produced it and could be forwarded to somebody that check
would have refused.

The redirect is not an implementation detail, it is the security property: the
bytes leave from an origin that is **not** the application's, so even a
hypothetical content-type escape on an uploaded file has no same-origin document
to act against. Ticket 2's CSP names that origin in `img-src`
(`ASSET_ORIGIN`, substituted into `nginx.conf.template` at container start).

`authorize_asset_access` in `app/routes/assets.py` is the single place that
decides. Today it admits authors only; ticket 5 adds the learner branches
(catalog-visible, or assigned) there and nowhere else. Anyone not admitted gets
**404**, not 403 — whether a particular asset exists is not something to confirm
to someone who may not read it.

### 2. The bytes decide what a file is, not the client

`app/content/uploads.py` never consults the client's declared `Content-Type`.
It reads magic bytes, and then requires the **filename extension to agree** with
what it found — so both the bytes and the name have to be honest, not either one
alone. A real PNG named `.jpg` is refused, and so is an executable named `.pdf`.

- Images: `png`, `jpeg`, `webp`, `gif`. **SVG is rejected outright**, checked
  before either allowlist and for both kinds, so an SVG renamed `logo.png` is
  refused by name (`svg_not_allowed`) rather than falling out as "unrecognised".
- Attachments: `pdf`, plus `docx`/`xlsx`/`pptx` verified by opening the ZIP and
  matching the OOXML main part declared in `[Content_Types].xml` — which is what
  keeps **macro-enabled** formats out, since a `.docm` declares a different
  string. `txt`/`csv` must decode as UTF-8, carry no control characters, and not
  begin with `<`: a stored `.txt` that is really HTML is a stored page waiting
  for a content-type mistake.
- Attachments are stored with `Content-Disposition: attachment` (RFC 6266, both
  the ASCII `filename` and the percent-encoded `filename*`) **and** a
  `Content-Type` of `application/octet-stream`, both set on the object so they
  hold however it is later fetched. S3 cannot emit an
  `X-Content-Type-Options: nosniff` response header on an object, so the PRD's
  "non-sniffable content type" has to be the type itself: an octet-stream marked
  as an attachment is downloaded by every browser rather than rendered, so there
  is no declared type for a sniffing heuristic to disagree with. The true
  sniffed type stays on the database row, which is what the authoring UI shows,
  and the filename extension is what opens the saved file. Images are the
  deliberate exception — they have to render, so they keep their real type,
  which is safe because it is one of four image types verified from the bytes and
  delivered under a CSP that only permits them in an image context.

Hand-rolled rather than libmagic or a detection package: the allowlist is ten
types, the checks fit on a screen, and a third-party heuristic's output would
have to be mapped onto this allowlist anyway. `tests/test_upload_sniffing.py`
exercises it directly, including the renames.

### 3. Nothing is persisted before it is known to be acceptable

Per-file caps (5 MB image, 20 MB attachment) and the per-module total (100 MB)
are all checked before either a row or an object is written. All three are
settings, so a deployment can raise them without a code change.

Be precise about what the in-handler cap does and does not buy: Starlette parses
the whole multipart body (spooling past 1 MB to a temp file) *before* the handler
is entered, so by the time `_read_within_cap` refuses a 24 MB "image", those
bytes have already been received. The guard that actually stops a hostile body
reaching the application is nginx's `client_max_body_size 25m`. The in-handler
cap is what guarantees nothing is **persisted**.

Write ordering is deliberate: the row is flushed, *then* the object is written,
*then* the transaction commits. A failed insert leaves nothing in the bucket; the
reverse order would strand an object with no row pointing at it. Deletion
mirrors it — the object is removed before the commit, so a store that refuses
leaves the row alongside the object it describes.

## Two things that are deliberately *not* here

- **Asset upload is not a `draft_revision` mutation.** Adding an asset is
  additive — it cannot overwrite a colleague's sentence — and bumping the token
  would invalidate the author's own next page save, so inserting an image would
  409 on the very save that references it.
- **Deleting an in-use asset is allowed.** The author is told how many pages
  embed it before they confirm (`referenced_by_pages`, computed with a jsonpath
  over the stored document trees). Refusing outright would leave no way to
  remove material that has to go; the guard is telling them, not stopping them.

## A local-environment caveat

LocalStack Community **does not enforce S3 request authorization**. Locally, an
unsigned `GET` against the bucket succeeds — and it does so for a bucket
LocalStack creates itself, with no involvement from this code. The backend does
set the public-access block and default encryption on startup (mirroring what
terraform will set, so the local environment is not more permissive by
configuration), and no code path grants a public ACL, but *enforcement* of the
private-bucket property only exists in a real deployment. Do not read the local
behaviour as the deployed posture. Terraform stands the real bucket up in
ticket 14.
