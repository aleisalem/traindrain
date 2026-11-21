Status: ready-for-agent

# Release 2.5 — Packaged Content (SCORM)

## Problem Statement

Many organisations already own awareness training as SCORM packages — bought from vendors or built in authoring tools. Today they can only re-author that material as native pages, which is lossy for interactive and media-heavy content and often impossible for packages whose source is long gone.

SCORM is not a document format; it is a runtime. A package is third-party HTML and JavaScript that must execute, and it reports progress by calling a JavaScript API. That creates two hard problems:

1. **Hostile code in an authenticated product.** Hosted on the application's own origin, a package could read the session cookie and call every API as the learner. It has to run somewhere it can do no harm.
2. **Self-reported results.** The completion signal comes from code running in the learner's browser, so it cannot be verified the way a server-graded quiz can.

## Solution

Add a **SCORM module type**. An author uploads a SCORM 1.2 or 2004 package; the platform validates and unpacks it, and learners play it in an iframe served from a **separate sandbox origin** that has no access to the application's cookies. A small SCORM API shim on the sandbox origin implements the 1.2 and 2004 run-time APIs and relays calls by `postMessage` to the application, which records them through authenticated backend endpoints. The package never sees a token.

A SCORM module is a first-class module — assignable, targetable, taggable, searchable, catalog-listable, usable in campaigns, versioned, translatable, duplicable, deletable, and exportable — except where a feature does not make sense for an opaque package (page editor, platform quiz, document import). Its completion feeds the same completion notion native modules use, so campaigns and sequencing treat it identically. Because the signal is self-reported, the roster says so.

## User Stories

### Authoring

1. As a Content Manager, I want to upload a SCORM package as a new module, so that I can reuse existing training.
2. As a Content Manager, I want the package's SCORM version detected automatically, so that I do not have to know it.
3. As a Content Manager, I want to give a SCORM module a title, description, language, tags and estimated duration, so that it is findable like any module.
4. As a Content Manager, I want a clear error when a package is rejected and why, so that I can fix or replace it.
5. As a Content Manager, I want a multi-SCO or sequencing-based package refused with a clear message, so that I know the limitation.
6. As a Content Manager, I want to test-play a package as a learner would without recording progress, so that I can check it before publishing.
7. As a Content Manager, I want to upload a new package to an existing SCORM module as a new version, so that I can update material.
8. As a Content Manager, I want to choose `minor` or `substantive` for each republish and see how many learners it affects first, so that I decide knowingly.
9. As a Content Manager, I want a substantive republish to supersede completions and reset progress, as for native modules, so that learners redo changed material.
10. As a Content Manager, I want to publish, unpublish and toggle catalog visibility, so that I control who can find it.
11. As a Content Manager, I want to view the version history of a SCORM module, so that I can see what was replaced.
12. As a Content Manager, I want to link SCORM modules as language variants, so that one assignment serves a mixed-language workforce.
13. As a Content Manager, I want to duplicate a SCORM module, with its own copy of the package, so that deleting the original never breaks the copy.
14. As a Content Manager, I want to delete a SCORM module, purging every version's files and leaving a tombstone, so that deletion is real and records remain.
15. As a Content Manager, I want to export a SCORM module, including the original package, and import it elsewhere, so that I can back up and move content.
16. As a Content Manager, I want to download the original package I uploaded, so that I never depend on the platform to keep my source.
17. As a Content Manager, I want to be told a platform quiz cannot be added to a SCORM module, so that I am not confused by two scores.

### Learner experience

18. As a learner, I want to launch an assigned SCORM module in the browser, so that I can take it like any other module.
19. As a learner, I want my progress saved so I can resume where I left off, so that closing the tab does not lose my place.
20. As a learner, I want the module marked complete when the package reports completion or a pass, so that my record is accurate.
21. As a learner, I want my score shown when the package reports one, so that I see my result.
22. As a learner, I want to retake a SCORM module, resetting its saved data, so that I can try again.
23. As a learner, I want the module to resolve to my preferred language when variants exist, so that I read in my language.
24. As a learner, I want a SCORM module in a campaign to count toward the campaign like any module, so that the path is seamless.
25. As a learner, I want a SCORM module that is locked by sequencing to be unreachable, so that order is enforced.
26. As a learner, I want a clear message if the package fails to load, so that I can report it.
27. As a learner, I want the player to work in light, dark and colour-blind-friendly themes around it and in English and German, so that the surrounding experience is consistent.
28. As a learner on a keyboard or screen reader, I want the player frame to be properly labelled and focusable, so that the surrounding experience is accessible, even though the package's own content is out of the platform's control.

### Security

29. As a platform owner, I want packages to run only on a separate origin, so that they can never read the session cookie.
30. As a platform owner, I want the sandbox origin to serve nothing but package files, so that it holds no other data.
31. As a platform owner, I want only the application origin allowed to frame the sandbox origin, so that no other site can embed a package.
32. As a platform owner, I want the `postMessage` bridge to verify the origin on both sides and ignore anything else, so that it cannot be spoofed.
33. As a platform owner, I want the package never to receive a token or credential, so that it cannot act as the learner.
34. As a platform owner, I want upload to resist zip bombs, path traversal and symlinks, so that a hostile archive cannot harm the server.
35. As a platform owner, I want the manifest parsed with external entities and DTDs disabled, so that XML attacks fail.
36. As a platform owner, I want only allowlisted file types accepted and the whole package refused if anything else appears, so that no server-side executable content is hosted.
37. As a platform owner, I want media checked against its actual bytes, not its extension, so that a disguised file is caught.
38. As a platform owner, I want files served with correct content types and `nosniff`, so that a browser never reinterprets them.
39. As a platform owner, I want access to package files gated by short-lived signed credentials issued only to authorised learners, so that a package URL is not a public link.
40. As a platform owner, I want run-time API values validated server-side for the SCORM version in use, so that malformed data is rejected with the proper SCORM error code.
41. As a platform owner, I want the stored run-time data capped at 64 KB per learner per package, so that a package cannot fill the database.
42. As a platform owner, I want completion accepted only for an authenticated learner with an initialised session, so that unauthenticated calls cannot complete anything.
43. As a platform owner, I want a completion arriving unrealistically soon after launch to be flagged but accepted, so that fakery is visible without breaking legitimate short packages.

### Reporting and privacy

44. As an Administrator, I want SCORM completions marked "self-reported" in the roster, so that I do not mistake them for verified results.
45. As an Administrator, I want a flagged fast completion visible in the roster, so that I can review it.
46. As a Content Manager, I want SCORM modules in group-level reports through the same counts as other modules, so that reporting is uniform.
47. As an Administrator, I want package upload, replacement, completion, score and flags audit-logged, so that I can trace them.
48. As a data subject, I want free-text and saved-state fields the package stored about me deleted when my account is erased, so that my erasure right is honoured.
49. As an Administrator, I want status, score and timestamps to remain against the anonymised tombstone after an erase, so that proof of completion survives.

### Operations

50. As a developer, I want `docker-compose` to start a sandbox origin on its own port, so that the isolation property holds locally.
51. As an operator, I want a Terraform stack for the private package bucket and the sandbox CDN on a separate registrable domain, so that production matches local behaviour.
52. As an operator, I want the sandbox signing key kept in a secret manager, never in the repository, so that credentials stay safe.

## Implementation Decisions

- **Module type:** a SCORM module is an ordinary module row with `module_type = "scorm"`. All shared behaviour — assignment, targeting, catalog, search, tags, campaigns, reminders, reporting, publish, supersession, translation groups, duplicate, delete tombstone — is reused through the existing code, branching on type only where behaviour must differ. The roadmap's earlier "opaque and unversioned" wording is superseded and ROADMAP is updated.
- **Versions:** each upload creates an immutable version row pointing at its own object-store prefix under a random package id, under the existing immutability trigger. Old prefixes are retained as native snapshots are. Duplicate copies the prefix; delete purges every version's objects and leaves the existing tombstone.
- **Not applicable to SCORM:** page editor, page preview (replaced by author test-play that records nothing), document import, and a platform quiz (a 409 on attempt to attach one). The package's own pass or completion is the module's completion for campaigns and sequencing, via the single completion notion Release 2 establishes.
- **Upload pipeline:**
  - Reuses the existing zip defences — entry count, per-entry compression ratio, total size, a shared read budget, strict entry-name checks, no bulk extraction, no symlinks — with a larger overall cap (about 200 MB) given media.
  - `imsmanifest.xml` is required at the root and parsed with a hardened parser (no DTDs, no external entities). SCORM 1.2 and 2004 any edition are accepted; version is detected from the manifest.
  - Single-SCO packages only. Multiple SCOs or sequencing and navigation models are refused (422) with a clear message.
  - An extension allowlist covers web assets (html, js, css, json, xml, images, audio, video, fonts). Anything else rejects the whole package. Media is sniffed from bytes.
  - Files are stored under the package prefix with content types set from the allowlist.
  - No malware scanning; the sandbox origin is the mitigation.
  - The original archive is stored so authors can download it and so export can include it.
- **Sandbox origin:**
  - A distinct origin from the application, not a subdomain its cookies reach; the application's session cookie remains host-only.
  - Serves only the package prefix, with a strict CSP, `X-Content-Type-Options: nosniff` and `frame-ancestors` limited to the application origin. The application's own CSP adds a `frame-src` naming the sandbox origin, in the same way `img-src` names `ASSET_ORIGIN`.
  - File access is gated by short-lived signed credentials issued by the backend only to a learner authorised for the module by the same single access decision used for native modules.
  - The player is embedded in a sandboxed iframe whose permissions are limited to what packages need on their own origin.
- **SCORM API shim:** served from the sandbox origin; implements the 1.2 `API` and 2004 `API_1484_11` objects; relays each call to the parent window by `postMessage`. The application verifies message origin and source frame, and calls authenticated backend endpoints; the sandbox verifies the parent's origin the same way. No token or cookie crosses to the package.
- **Run-time data:**
  - The backend stores per-learner, per-package-version CMI state (status, score, location, suspend data, session time, and other fields the data model allows).
  - Values are validated per SCORM version (vocabularies, score ranges, time formats); invalid sets return the SCORM error code.
  - The blob is capped at 64 KB.
  - Completion is `completed` or `passed` (1.2 `lesson_status`; 2004 `completion_status` or `success_status`) and writes the same completion record native modules use.
  - Retake resets the stored state.
- **Self-reported trust:** completion requires an authenticated learner and an initialised session. A completion arriving under about 10 seconds after launch is flagged but accepted. Reports mark SCORM completions "self-reported" and show the flag. Completion, score and flags are audit-logged. A SCORM score is shown and reported but does not feed a platform quiz.
- **Substantive republish** supersedes completions and resets stored run-time state, as the native equivalent does.
- **Translations:** each variant has its own package; linking, primary selection and the fixed-variant rule are unchanged.
- **Export and import:** the native export archive includes the original package; import restores it through the full validation pipeline. Nothing in the archive is trusted beyond an ordinary upload.
- **Privacy:** on erase, suspend data, the raw CMI blob and free-text fields are deleted; status, score and timestamps remain against the tombstone.
- **Frontend:** a SCORM upload and version panel on the module screen, an author test-play, the player page with the shim bridge, and "self-reported" marking in the roster. UI follows existing patterns; all strings in English and German.
- **Infrastructure:**
  - Local: a `scorm-sandbox` service in `docker-compose` on its own port, proxying a private LocalStack bucket and setting the headers above; its config templated at start like the existing frontend config.
  - AWS (`.deploy/dev`): a separate private package bucket (public access blocked, SSE, versioning, lifecycle rules), a CloudFront distribution on a separate registrable domain using Origin Access Control and signed cookies, with the key pair in Secrets Manager and a least-privilege IAM policy for the backend.
  - Release 0 resources (cluster, roles, domain) stay as input variables, as in Release 1.
  - Dev docs and `.deploy/dev/README.md` are updated.

## Testing Decisions

- **A good test** asserts what a caller observes through the highest seam — responses, what a learner can or cannot reach, stored completion, audit rows — not internals.
- **Backend seam:** the HTTP API against real Postgres with faked S3, in the existing pattern. Cover: valid 1.2 and 2004 packages accepted and version-detected; rejection of multi-SCO and sequencing packages, a missing or malformed manifest, XML entity and DTD payloads, zip bombs, traversal and symlink entries, a disallowed extension, and a disguised media file; signed-credential issuance only for authorised learners; run-time API validation and SCORM error codes; the 64 KB cap; completion requiring an initialised authenticated session; fast-completion flagging; retake reset; versioning and minor versus substantive supersession; translation linking; duplicate and delete purging every prefix; export and import round trip with revalidation; the 409 on attaching a quiz; completion feeding campaign completion and sequencing; self-reported marking in the roster; and erase behaviour.
- **Frontend seam:** Vitest and React Testing Library for the upload and version panel and the player page, plus one dedicated test of the `postMessage` bridge asserting it ignores messages from the wrong origin or source and never forwards credentials.
- **Sandbox configuration test:** assert the sandbox config emits the expected CSP, `nosniff` and `frame-ancestors`, and that the application's CSP names the sandbox origin.
- **Terraform:** `terraform validate` only.
- **Prior art:** Release 1's asset upload sniffing, native import and document import zip-defence tests, publishing and supersession tests, and CSP configuration test.
- No browser end-to-end test; cross-origin behaviour is covered at the configuration and bridge level.

## Out of Scope

- Multi-SCO packages, SCORM sequencing and navigation, and packages relying on LMS features beyond the run-time API.
- Other packaged formats (xAPI, cmi5, AICC).
- Server-side verification of a package's reported result.
- Malware scanning of uploaded packages.
- A platform quiz on top of a SCORM module.
- Page editing, preview or document import for SCORM modules.
- Video upload and transcoding (separate roadmap item).
- Adding the Release 0 baseline AWS stack.

## Further Notes

- Depends on Release 2: SCORM completion feeds the single completion notion campaigns and sequencing use, and the roadmap's earlier assumption that SCORM shares almost nothing with the native model is replaced by the decision that it shares the module, assignment, version and translation machinery and differs only in content and runtime.
- Self-reported results are inherent to SCORM; authors needing verifiable grading should use native modules with a quiz, and the UI and docs say so.
- The sandbox origin must be a distinct registrable domain in production so that no cookie scoped to the application's domain can reach it.
