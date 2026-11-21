# Tickets: Release 2.5 — Packaged Content (SCORM)

A SCORM module type: validated upload of single-SCO SCORM 1.2/2004 packages, playback on a separate sandbox origin with a `postMessage`-bridged run-time API, and the full native module machinery (versioning, translations, assignment, campaigns, reporting) except where it makes no sense for an opaque package. Source spec: [PRD.md](PRD.md).

Every ticket here is blocked by Release 2 being complete, because SCORM completion feeds the single completion notion that campaigns, sequencing and reports use.

Work the **frontier**: any ticket whose blockers are all done. After ticket 2, tickets 3 and 7 can proceed in parallel; after ticket 4, tickets 5 and 6 can.

## 1. SCORM module type and package upload

**What to build:** A Content Manager uploads a SCORM package and gets a SCORM module draft, or a clear reason it was refused. The platform detects whether it is SCORM 1.2 or 2004, rejects packages it cannot support (multiple SCOs, sequencing and navigation models, a missing or malformed manifest, disallowed file types), and keeps the original archive so it can be downloaded and exported later. Metadata (title, description, language, tags, estimated duration) works like any module. Nothing plays yet.

**Blocked by:** Release 2 complete.

- [ ] Modules gain a `module_type` (`native` default, `scorm`); existing code branches on it only where behaviour must differ
- [ ] `POST /api/content/modules/scorm-import` accepts a package plus language and metadata and always creates an unpublished draft in its own new translation group
- [ ] Zip defences reuse Release 1's: entry count, per-entry compression ratio, total size (cap about 200 MB), shared read budget, strict entry-name checks, no bulk extraction, no symlinks
- [ ] `imsmanifest.xml` required at the root, parsed with DTDs and external entities disabled; SCORM 1.2 and 2004 (any edition) accepted and the version detected; multiple SCOs or sequencing and navigation models refused with 422 and a clear message
- [ ] Extension allowlist for web assets; any other file rejects the whole package; images and media sniffed from bytes
- [ ] Files stored under a random package-id prefix with content types from the allowlist; the original archive stored; per-package and per-module size limits enforced before persisting
- [ ] Page editor, document import and platform-quiz routes refuse SCORM modules (409 for the quiz)
- [ ] `scorm_package_uploaded` audit entry with version and size
- [ ] Frontend: SCORM upload entry point on `/content` and a SCORM metadata screen, EN/DE, all themes
- [ ] Backend tests: valid 1.2 and 2004 packages, multi-SCO and sequencing refusal, missing and malformed manifest, XML entity and DTD payloads, zip bomb, traversal and symlink entries, disallowed extension, disguised media; frontend tests for the upload flow
- [ ] README's supported-features section updated

## 2. Sandbox origin and player launch

**What to build:** A learner (or an author test-playing) opens a SCORM module and the package loads and runs inside the page, served from a separate origin that cannot read the application's cookies. The sandbox serves only that package's files, carries its own strict security headers, and is reachable only through short-lived signed credentials the backend issues solely to someone authorised to read the module under the single access decision native modules already use. Author test-play records nothing. Locally this is a second origin on its own port, so the isolation property holds in development too.

**Blocked by:** 1

- [ ] A `scorm-sandbox` service in `docker-compose` on its own port serves a private LocalStack bucket prefix with a strict CSP, `X-Content-Type-Options: nosniff`, and `frame-ancestors` limited to the application origin; its config is templated at start like the existing frontend config
- [ ] The application's own CSP names the sandbox origin in `frame-src`; the application's session cookie stays host-only
- [ ] The backend issues short-lived signed access only to a learner who passes the access decision (assigned, catalog, or active-campaign route and not locked) or to an author test-playing; everyone else gets 404
- [ ] The player page embeds the package in an iframe with only the sandbox permissions packages need, labelled and focusable
- [ ] Author test-play launches without creating any learner state
- [ ] Clear failure message in the player when the package cannot load
- [ ] Backend tests: signed access granted and refused appropriately, expiry; sandbox configuration test asserting CSP, `nosniff`, `frame-ancestors`, and the application CSP's `frame-src`; frontend tests for the player page

## 3. SCORM run-time API, completion and resume

**What to build:** A learner works through the package and the platform records it. The package talks to a SCORM API shim on the sandbox origin, which relays calls by `postMessage` to the application, which records them through authenticated backend endpoints; the package never sees a token or cookie. Progress is saved so the learner resumes where they left off, a reported score is shown, and when the package reports completion or a pass the module is marked complete using the same completion record native modules write — so campaigns and sequencing treat it identically. Completion needs an authenticated learner with an initialised session; one arriving unrealistically soon after launch is flagged but accepted. A learner can retake, which resets the saved state.

**Blocked by:** 2

- [ ] Shim implements the 1.2 `API` and 2004 `API_1484_11` objects and forwards each call to the parent by `postMessage`; the application verifies message origin and source frame, and the sandbox verifies the parent's origin the same way; messages from anywhere else are ignored
- [ ] Backend endpoints store per-learner, per-package-version run-time state, validated per SCORM version (vocabularies, score ranges, time formats), returning the proper SCORM error code on invalid values
- [ ] Stored state capped at 64 KB per learner per package; over-cap writes are rejected
- [ ] `completed` or `passed` (1.2 `lesson_status`; 2004 `completion_status` or `success_status`) writes `completed_at` and the version through the shared completion path; sets before initialisation or without an authenticated session are refused
- [ ] A completion under about 10 seconds after launch is flagged and accepted; score, flag and session time are stored
- [ ] Resume restores location and suspend data; retake resets stored state
- [ ] Campaign completion and sequential unlocking treat a SCORM completion exactly like a native one
- [ ] Frontend: bridge component, score and status display, retake control
- [ ] Backend tests: validation per version, error codes, cap, initialisation and auth requirements, fast-completion flag, resume, retake, campaign and sequencing integration; frontend tests including a dedicated bridge test asserting wrong-origin and wrong-source messages are ignored and credentials are never forwarded

## 4. Versioning, publishing and catalog

**What to build:** A SCORM module is published, republished and withdrawn like any native one. Each upload of a new package creates an immutable version with its own stored files; the author picks `minor` or `substantive` every time and sees how many learners a substantive choice affects. A substantive republish supersedes completions and resets stored run-time state so learners redo the changed material. Authors can publish, unpublish, toggle open-catalog visibility, see the version history, and download the original package.

**Blocked by:** 3

- [ ] Uploading a new package to an existing SCORM module creates a new draft package; publish writes an immutable version row pointing at its own package prefix, covered by the existing immutability trigger
- [ ] Publish requires explicit `revision_kind` with no default; `substantive` supersedes completions and clears run-time state; the revision-impact endpoint reports the count first
- [ ] Publish, unpublish and catalog toggle work through the existing routes; old version prefixes are retained
- [ ] Version history lists package versions for authors; the original package of any version is downloadable by authors
- [ ] Attaching a platform quiz is refused (409)
- [ ] Learners always play the published version, never a draft
- [ ] Frontend: SCORM version panel with publish dialog and impact message, test-play of the draft, original-package download
- [ ] Backend tests: version immutability, minor versus substantive, state reset, learners never seeing a draft, quiz refusal; frontend tests for the dialog

## 5. Translations, duplicate, delete, export and import

**What to build:** SCORM modules behave like native ones where content moves. Variants in different languages are linked into a translation group, each with its own package. Duplicating copies the stored package, so deleting the original never breaks the copy. Deleting purges every version's files and leaves the usual tombstone. Exporting includes the original package, and importing restores it through the full validation pipeline, trusting nothing in the archive beyond an ordinary upload.

**Blocked by:** 4

- [ ] Linking a SCORM module into a translation group and primary selection work through the existing routes; mixing a SCORM variant with a native variant in one group is a 409
- [ ] Duplicate copies every stored version's package into its own new prefix
- [ ] Delete purges every version prefix and the original archives and leaves the tombstone; learner progress rows are retained
- [ ] Export includes the package; import runs the ticket 1 validation again and creates an unpublished draft
- [ ] Frontend: nothing new beyond existing controls recognising SCORM modules
- [ ] Backend tests: link rules, duplicate independence, delete purging, export and import round trip, hostile imported package rejected

## 6. Reporting, audit and erase

**What to build:** Reports say plainly that a SCORM result is self-reported. The Administrator's roster and CSV mark SCORM completions as such and show the fast-completion flag; Content Managers see SCORM modules in the same group-level counts as any other. Upload, replacement, completion, score and flag are all audit-logged. When a user is erased, the free text and saved state a package stored about them are deleted, while status, score and timestamps remain against the anonymised tombstone.

**Blocked by:** 4

- [ ] Roster and CSV gain a self-reported marker and fast-completion flag for SCORM completions; a short note in the report UI explains that these cannot be verified like platform quizzes
- [ ] Group-level counts for Content Managers are unchanged in shape and still show no names
- [ ] Audit entries for upload, new version, completion, score and flag
- [ ] The existing user-erase action deletes `suspend_data`, the raw state blob and free-text fields for SCORM state and keeps status, score and timestamps
- [ ] Frontend: self-reported marker and note
- [ ] Backend tests: roster and CSV markers, no leakage to Content Managers, audit entries, erase behaviour; frontend tests for the marker

## 7. AWS infrastructure and wrap-up

**What to build:** Production matches local behaviour. Terraform declares a separate private package bucket and a CDN on a separate registrable domain, with signed access from the backend. The release is documented and security-reviewed.

**Blocked by:** 2

- [ ] `.deploy/dev` declares a private package bucket (public access blocked, SSE, versioning, lifecycle rules for aborted multipart uploads and expiring noncurrent versions), separate from the module-assets bucket
- [ ] A CloudFront distribution on a separate registrable domain, not a subdomain the application's cookies reach, using Origin Access Control and signed cookies; the response-headers policy matches the local sandbox's CSP, `nosniff`, and `frame-ancestors`
- [ ] The signing key pair held in Secrets Manager and injected at runtime, never present in the repository
- [ ] Least-privilege IAM policy for the backend scoped to the package bucket; Release 0 resources (cluster, roles, domain) remain input variables; `terraform validate` runs clean
- [ ] `.deploy/dev/README.md`, `docs/references/infrastructure.md`, the README's project structure, running-locally and AWS sections updated; a brief summary of each feature added under `docs/references/`
- [ ] `security-scan` run over the release's changes, with particular attention to the bridge and sandbox, and findings recorded
