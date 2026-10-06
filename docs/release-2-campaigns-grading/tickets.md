# Tickets: Release 2 — Campaigns & Grading

Campaigns (first-class collections of modules targeted at groups and individuals, with a draft/active/suspended/closed lifecycle, optional sequencing and campaign-level reminders) and graded quizzes (server-graded, versioned with the module, gating completion). Source spec: [PRD.md](PRD.md). Builds on Release 1's assignment, access, reminder, reporting, and publishing machinery; nothing in Release 1 is replaced.

Work the **frontier**: any ticket whose blockers are all done. Tickets 1 and 8 can start immediately and run in parallel (campaign track and quiz track). Ticket 9 needs `ux-discovery` for the quiz-taking flow first, and ticket 1 for the campaign builder.

## 1. Campaign drafts

**What to build:** A Content Manager creates a campaign and builds it up in draft: a name, description, an ordered list of modules (each marked `mandatory` or `recommended`), group targets, optional start and due dates, an automatic-reminders toggle, and a `sequential` toggle. They see only the campaigns they created. Anyone else, including other Content Managers, gets a 404 on every campaign route. A draft is invisible to learners and sends nothing. Modules are referenced by translation group, so a translation added later is covered automatically. Content Managers see group names, descriptions and member counts only when picking targets. Individual targets, collaborators and activation come in later tickets.

**Blocked by:** None — can start immediately.

- [ ] Migrations create campaigns, campaign modules (translation group, position, requirement), and campaign targets (`user`|`group`, non-foreign-key `target_id` checked at the route, as assignments do), with the same UUID and timezone conventions as earlier releases
- [ ] `GET|POST /api/content/campaigns` and `GET|PATCH /api/content/campaigns/{id}` create, list, read and update; module ordering and requirement are editable; `created_by` is set server-side and never accepted from the client
- [ ] A Content Manager sees only campaigns they created; any other campaign is a 404 on every route, never a 403
- [ ] A group target resolves through the existing counts-only group listing; an individual target is a 403 for a Content Manager
- [ ] Referencing an unpublished or deleted module is allowed in draft but reported per module in the response
- [ ] `campaign_created` and `campaign_updated` are audit-logged
- [ ] Frontend: campaign list and builder (module ordering, targets, dates, toggles) under the content area, in EN/DE, all three themes, responsive, with navigation entry visible to Content Managers and Administrators only; builder design settled via `ux-discovery` first
- [ ] Backend tests through the API: permission matrix and 404-versus-403 behaviour, validation, ordering, audit entries; frontend tests for the builder
- [ ] README's supported-features section updated

## 2. Collaborators, individual targets and presence

**What to build:** The creator of a campaign adds other Content Managers as collaborators, who can then edit it and (once the lifecycle exists) change its status. Only the creator or an Administrator can add or remove collaborators, or delete a draft. Administrators see and edit every campaign, can target named individuals, and can reassign the creator of an orphaned campaign. Anyone editing a campaign sees who else has it open, as on module authoring.

**Blocked by:** 1

- [ ] Migration creates campaign collaborators; collaborators must hold Content Manager or Administrator, otherwise 409
- [ ] `POST|DELETE` collaborator routes restricted to the creator and Administrators; a collaborator attempting them is a 403, and non-participants still get a 404
- [ ] A collaborator has the creator's edit rights on metadata, modules and targets; draft deletion remains creator or Administrator only
- [ ] An Administrator can list and edit every campaign, add individual targets, and reassign the creator; an erased creator or a creator who lost the role leaves collaborators intact
- [ ] Presence heartbeat and editor list reuse the Release 1 module presence pattern for campaigns
- [ ] Collaborator and ownership changes are audit-logged
- [ ] Frontend: collaborator panel, Administrator-only individual-target option, presence avatars
- [ ] Backend tests for every row of the permission matrix and orphan handling; frontend tests for the panel and Administrator gating

## 3. Activation and the learner's campaign view

**What to build:** A campaign author activates a campaign and its targeted learners see it. Activation is refused unless every mandatory module is published and there is at least one target. Learners' access to a campaign's modules is derived live from their current group membership, so a late joiner sees it and a leaver loses it but keeps what they finished. Each currently-targeted learner gets one activation email in their own language. "My learning" groups modules under their campaign with a progress bar ("3 of 5 required done"), distinguishes mandatory from recommended, and shows the due date and overdue state. A campaign is complete when every mandatory module is complete, computed on every read; a substantively republished module reopens it. A start date activates the campaign through the existing daily job. Closing a campaign stops reminders and new starts while keeping every record readable.

**Blocked by:** 1

- [ ] `POST /api/content/campaigns/{id}/activate` and `.../close` with the draft → active → closed transitions; any other transition is a 409
- [ ] The single module read-access decision gains a campaign branch: a published module is readable if reachable through an active campaign the caller is targeted by; learner routes and asset delivery both ask that one decision
- [ ] Campaign completion is computed live from module progress and never stored; completions superseded by a substantive republish do not count
- [ ] Activation email sent once per currently-targeted learner via the existing mailer in their preferred language; learners joining later are not emailed retroactively
- [ ] The daily job entrypoint activates campaigns whose start date has arrived and does nothing twice on a rerun
- [ ] Closed campaigns block starting new modules but keep progress and records readable
- [ ] `GET /api/me/modules` (or its successor) returns campaign grouping, requirement per module, due date, overdue flag, and campaign progress
- [ ] Frontend: "My learning" campaign groups with progress bar and badges; activation controls in the builder
- [ ] `campaign_activated` and `campaign_closed` are audit-logged
- [ ] Backend tests: late joiner and leaver, mixed-route access, substantive republish reopening, start-date activation idempotence, validation refusals; frontend tests for the grouping and progress

## 4. Suspend and resume

**What to build:** An author suspends an active campaign and its modules disappear from learners' view, then resumes it. Suspension removes only the campaign's own route to a module: a module the learner can still reach through a direct assignment or the open catalog stays there as a normal module, and one with no other route returns 404 and leaves "My learning". Progress is kept. Reminders and the `overdue` flag are frozen while suspended, and due dates never shift on their own. Resuming a campaign whose due date has passed prompts for a new date, and the campaign carries a visible warning until it is set.

**Blocked by:** 3

- [ ] `POST .../suspend` and `.../resume` with the transitions active ⇄ suspended; other transitions are a 409; collaborators may use them
- [ ] Access decision tests the campaign's own route only; direct-assignment and catalog fallbacks keep working
- [ ] Progress rows untouched; the `overdue` flag is never true for a suspended campaign's modules through the campaign route
- [ ] Resume with a lapsed due date succeeds, flags a "due date lapsed" state in the response, and clears it once an author sets a later date
- [ ] Frontend: suspend/resume controls, the new-due-date prompt, and the lapsed warning
- [ ] `campaign_suspended` and `campaign_resumed` are audit-logged
- [ ] Backend tests: fallback routes, 404 when no other route, frozen overdue, lapsed-date flow; frontend tests for the prompt

## 5. Sequential campaigns

**What to build:** When an author marks a campaign sequential, module N is locked until module N−1 is complete or passed. The lock is enforced on the server, so a locked module is unreachable even by typing its URL. The learner sees which modules are locked and what unlocks each.

**Blocked by:** 3

- [ ] The access decision returns a locked result for a sequential campaign's module whose predecessor is incomplete; viewer routes respond accordingly and never serve its pages or assets
- [ ] "Complete or passed" is evaluated against one completion notion so that quiz-gated and (later) SCORM completions feed it
- [ ] A learner reaching the module through another route (direct assignment or catalog) is not locked by the campaign
- [ ] The learner API reports lock state and the prerequisite module
- [ ] Frontend: locked-module rendering with the unlocking prerequisite, keyboard- and screen-reader-friendly
- [ ] Backend tests: lock by direct URL and asset URL, unlock on completion, superseded completion relocking, other-route exemption; frontend tests for locked rendering

## 6. Active-campaign edit safeguards

**What to build:** An author can adapt a running campaign. Adding modules and targets is allowed. Removing a module or a target that has learner progress is blocked or asks for explicit confirmation after telling the author the affected number first. A draft that never went live can be hard-deleted; a campaign that ever activated never can. A module deleted elsewhere stays visible inside the campaign as an unopenable marker.

**Blocked by:** 3

- [ ] Add-module and add-target on an active campaign take effect for learners on their next read; newly targeted learners are not emailed retroactively
- [ ] An impact endpoint reports how many learners and records a removal would affect before it happens; removal with affected progress requires explicit confirmation
- [ ] Draft deletion by creator or Administrator only; deleting a campaign that ever activated is refused
- [ ] A module tombstoned by Release 1's delete appears in the campaign view marked unavailable and does not count toward mandatory completion
- [ ] Frontend: impact confirmation dialog and the unavailable-module marker
- [ ] Backend tests: impact counts, confirmation requirement, deletion rules, tombstone handling; frontend tests for the dialog

## 7. Campaign reminders

**What to build:** Learners are chased once per campaign, not once per module. A daily job sends each targeted learner a single email per campaign per day listing the mandatory modules they still owe, on the existing cadence (7 days before, 1 day before, on the due date, weekly while overdue), in the deployment timezone and the learner's language. Recommended modules are never chased. A module's Release 1 reminder is suppressed on any day the campaign reminder already covers it. Suspended and closed campaigns send nothing, and resuming sends no catch-up burst. An Administrator can nudge a campaign by hand, limited to once per campaign per day.

**Blocked by:** 3, 4

- [ ] The daily job reminds on campaigns where `auto_reminders` is on, a due date is set, the campaign is active, and the learner has outstanding mandatory modules; completed and superseded states are respected
- [ ] The one-email-per-learner-per-day cap is checked against the send log across campaign and module reminders; a second run the same day sends nothing
- [ ] Release 1 per-module reminders are suppressed for modules the campaign reminder covers
- [ ] No reminders for suspended or closed campaigns; after resume the next cadence step applies, with no catch-up
- [ ] `POST /api/content/campaigns/{id}/remind` is Administrator-only, rate-limited once per campaign per day against its own audit entry, and reports how many learners were actually reached
- [ ] Reminder email rendered in the recipient's `preferred_language`; `reminder_sent` audit entries
- [ ] Frontend: Administrator "Remind everyone outstanding" button reporting the real reach or the day's rate limit
- [ ] Backend tests: cadence, cap, suppression, suspension, resume, manual nudge limits; frontend test for the button

## 8. Quiz authoring and snapshotting

**What to build:** A Content Manager adds a quiz to a module draft: single-choice, multiple-choice and true/false questions with rich-text prompts from the existing validated subset, correct answers, and optional explanations; plus a pass mark (default 80%), an optional attempt cap, a shuffle toggle, and a reveal-correct-answers-after-pass toggle. They can try the quiz as a learner without recording anything. Publishing validates the quiz (at least one question, correct answers present, exactly one for single-choice and true/false, distinct non-empty options) and freezes it into the immutable version. Adding or changing a quiz on a module with completions follows the author's explicit `minor` or `substantive` choice, with the revision-impact count extended to show how many learners a substantive publish would supersede. Removing a quiz is always minor.

**Blocked by:** None — can start immediately.

- [ ] Migrations add quiz, question and option storage (with a `type` discriminator for future question types) and extend the version snapshot; the existing immutability trigger covers it
- [ ] Question prompts and explanations go through the same server-side ProseMirror validator as pages — rejected, never stripped
- [ ] `GET|PUT /api/content/modules/{id}/quiz` and question CRUD; correct answers are returned only to authors
- [ ] Publish refuses an invalid quiz with a clear 422; a valid one is snapshotted so later draft edits never change a published version
- [ ] The extended revision-impact endpoint counts learners affected by a quiz add or change; removing a quiz reports zero and requires no choice
- [ ] Author try-out grades server-side and records no attempt
- [ ] `quiz_updated` and publish audit entries note the quiz change
- [ ] Frontend: quiz editor on the module screen with all question types, settings and try-out, EN/DE, all themes
- [ ] Backend tests: validation matrix, snapshot immutability, revision-impact counts, injection attempts in prompts rejected; frontend tests for the editor

## 9. Quiz-taking, grading and completion gating

**What to build:** A learner reads a module that has a quiz, reaches the quiz after the last page, answers it, and sees their score and pass/fail immediately. The server grades everything, and no payload sent to a learner ever contains correctness data. Attempts are stored with score, timestamp, quiz version, answers and shuffle seed, can be resumed after closing the tab, and honour the attempt cap; submissions are rate-limited and checked against the attempt's own question set. After a failure the learner sees which questions were wrong but not the answers; correct answers and explanations are revealed after a pass only if the author allowed it. They choose to retake only the quiz (page progress kept) or retake the module (page progress cleared). The attestation stays locked until every page is viewed and the quiz is passed, and the completion record stores the winning score and quiz version. A learner mid-attempt when the module is republished finishes the quiz version they started.

**Blocked by:** 8 (and `ux-discovery` for the quiz-taking flow)

- [ ] `POST` start/resume attempt, `PUT` answer, and `POST` submit routes against the learner's resolved variant; payload carries question text and options only
- [ ] Single-choice and true/false match the one correct option; multiple-choice is all-or-nothing on the exact set
- [ ] Attempt cap enforced server-side with a clear exhausted state; submission rate-limited
- [ ] Completion requires all pages viewed, then a passing attempt, then the attestation; any other order is a 409; completion stores score and quiz version; modules without a quiz behave as before
- [ ] Retake-quiz-only keeps `pages_viewed`; retake-module clears it; both are explicit requests
- [ ] A republish during an in-progress attempt does not invalidate it; new attempts use the new version, and old attempts do not count toward the new version's cap
- [ ] Reveal of correct answers and explanations only after a pass and only when the author enabled it
- [ ] Frontend: the quiz-taking experience, result screen, retake choice, attempts-remaining message, fully keyboard- and screen-reader-operable with focus moved and results announced via a live region, engaging in all three themes and both languages
- [ ] Backend tests: grading for all three types, no correctness data in any learner response, forged or foreign question ids rejected, cap and rate limit, resume, gating order and 409s, both retake paths, mid-attempt republish; frontend tests including keyboard operation

## 10. Quizzes across translations, duplicate, export and import

**What to build:** Each language variant of a module carries its own quiz and settings, with a "copy settings from the primary variant" option when linking a translation. Linking is refused unless both variants have a quiz or neither does, so learners are never graded in one language and not the other. Duplicating, exporting and importing a module carry its quiz, and an imported quiz passes through exactly the same validators as an authored one.

**Blocked by:** 8

- [ ] Quiz is per module row; variants are authored independently
- [ ] Linking a variant into a group is a 409 when quiz presence differs; the response says which side lacks one
- [ ] "Copy from primary" copies settings (pass mark, cap, shuffle, reveal) and, optionally, question structure as a starting point for translation
- [ ] Duplicate produces a copy of the draft quiz; export includes the quiz in the manifest; import re-validates it and never trusts the manifest's own claims
- [ ] Frontend: copy-from-primary control and link-refusal message
- [ ] Backend tests: link refusals, copy behaviour, duplicate, export/import round trip, hostile imported quiz rejected; frontend tests for the control

## 11. Attempt administration and erase

**What to build:** An Administrator resets a learner's attempts on a module so they can try again, audit-logged. Attempts count across translation variants toward the cap, so switching language cannot dodge it. When a user is erased, their per-answer data is hard-deleted while the attempts survive only as de-identified aggregates (score, pass/fail, quiz version, timestamp) against the tombstone, so statistics stay correct and completion records remain.

**Blocked by:** 9, 10

- [ ] `POST` attempt-reset route, Administrator-only, audit-logged with module and learner
- [ ] Cap counts attempts across a translation group; a language switch keeps attempts and any prior pass
- [ ] The existing user-erase action deletes answer rows and detaches attempts from identity, leaving aggregates against the tombstone
- [ ] Reports computed after an erase still include the de-identified aggregates
- [ ] Frontend: Administrator reset control and the exhausted-attempts message pointing to it
- [ ] Backend tests: reset, cross-variant cap, erase deleting answers while keeping aggregates and completions; frontend test for the control

## 12. Campaign reports

**What to build:** "Did people do this programme?" answered with the Release 1 privacy split. A Content Manager sees, for each targeted group, how many learners completed, are in progress, have not started, are overdue or are suspended, plus average progress, and never a name or email. An Administrator sees the per-learner roster with each module's state, and can export it as CSV. A Content Manager can read only campaigns they may edit.

**Blocked by:** 3, 4

- [ ] `GET /api/content/campaigns/{id}/report` returns the caller-appropriate shape, decided on the server
- [ ] `GET .../report.csv` is Administrator-only
- [ ] Counts use the same live completion computation as the learner view, so a superseded completion reports as outstanding while keeping its prior record visible to Administrators
- [ ] Frontend: a campaign report panel reachable from the campaign and from the Reports area, CSV link shown only to Administrators
- [ ] Backend tests: shape per role, no names or emails for Content Managers, 404 for non-participants, CSV Administrator-only, suspended counted; frontend tests for panel and gating

## 13. Quiz reports, and Release 2 wrap-up

**What to build:** The module report shows quiz results: pass rate, average score and attempts-to-pass per group, and per-question percent-correct so authors can find broken or confusing questions. Administrators additionally see each learner's best score and attempt count in the roster and CSV. Individual answers appear in no report or CSV. This ticket also closes out the release: documentation, a statement that Release 2 needs no new infrastructure, and a security review.

**Blocked by:** 9, 11, 12

- [ ] Module report extended with group-level quiz statistics and per-question percent-correct for Content Managers; no names, no individual answers
- [ ] Administrator roster and CSV gain best score and attempt count; individual answers never present
- [ ] Statistics remain correct after a user erase
- [ ] Frontend: quiz section in the report panel
- [ ] README updated (features, structure, tests); a brief summary of each feature added under `docs/references/`; `docs/references/infrastructure.md` notes that Release 2 adds no new Terraform
- [ ] `security-scan` run over the release's changes and findings recorded
- [ ] Backend tests: statistics correctness, no answer leakage, post-erase correctness; frontend tests for the section
