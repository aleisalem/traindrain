# Release 1 security scan

Static security review of everything added in Release 1 (learning modules), diffed against
`main` at merge-base `62e449a`: 205 files, ~33k lines across 24 commits. Scope: HIGH-CONFIDENCE
vulnerabilities newly introduced by this release, excluding DoS/resource-exhaustion, rate
limiting, and secrets-on-disk (handled separately). The review was split across five areas —
file uploads/asset storage/delivery, native zip import/export + document conversion (Markdown/
DOCX/PDF), authorization/IDOR across module access/assignments/reporting, search/reminders/
email/audit logging, and frontend XSS/CSP + Terraform infra.

## Result

No findings met the bar (confidence ≥0.8, severity MEDIUM+, concrete exploit path).

## What was specifically verified (not just assumed)

- **Uploads**: content-type is sniffed from bytes before extension checks; SVG rejected
  outright; OOXML macro formats excluded by exact main-part match; asset delivery authorizes via
  the single `may_read_module` decision point before any row lookup, scoped `module_id` + `id`
  (no cross-module IDOR); unauthorized/nonexistent both 404 (no existence oracle).
- **Zip import/export**: strict allowlist entry-name matching (no `extractall`, no zip-slip),
  two independent zip-bomb defenses (declared-metadata check + a shared byte budget bounding
  actual reads), re-sniffing of every imported asset regardless of manifest claims, consistent
  ProseMirror re-validation on import.
- **Authorization**: individual-target assignments are 403'd for Content Managers server-side on
  both create and delete; `GET /api/content/groups` never leaks member identities;
  `report.csv` is its own Administrator-gated route, not a client-controlled format flag;
  translation-group variant resolution never trusts a client-supplied module id.
- **Search/reminders/email**: `search.py` is fully parameterized through SQLAlchemy (no f-string
  SQL); SES calls use structured API params (no CRLF header-injection surface); the
  reminder-timezone setting is validated via `ZoneInfo` before persistence; no audit-log-read
  endpoint exists at all.
- **Frontend/infra**: `dangerouslySetInnerHTML`/`innerHTML` are repo-wide banned (lint rule +
  test), page rendering goes through Tiptap's node-by-node React renderer; CSP has no
  `unsafe-inline`/`unsafe-eval`; Terraform IAM roles are tightly scoped (no `s3:*`, no
  `Resource: "*"`); the assets S3 bucket has public access fully blocked with SSE and versioning.

## Noted but out of scope

`app/content/document_import.py`'s DOCX zip-bomb check validates declared metadata only before
handing the file to `python-docx`'s `DocxDocument()`, which then decompresses every part
unbounded — unlike `transfer.py`'s native import, which caps actual reads against a shared byte
budget regardless of declared size. This is a resource-exhaustion concern, excluded by this
scan's rules, not a reported finding. Worth a follow-up ticket if DOCX import should be held to
the same bound as native import.
