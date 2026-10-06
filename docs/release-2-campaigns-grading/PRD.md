Status: ready-for-agent

# Release 2 — Campaigns & Grading

## Problem Statement

Release 1 can put a single module in front of a person or a group, but real awareness and compliance work is rarely one module. A phishing programme is five short modules over a month; an onboarding programme has a required order; a yearly refresher has a deadline for everyone. Today an author must create one assignment per module per target, keep their due dates aligned by hand, and has no way to say "this programme is paused" or to see how far a group has got through the whole thing. Learners get a flat list with no sense of a path.

Separately, "completed" currently means "I confirm I read this". For compliance content that is not enough: the platform cannot require that anyone understood the material. There is no way to ask a question, grade the answer on the server, or make a pass a precondition of completion.

Two constraints shape the design:

1. **A quiz is evidence too.** What a learner was graded against must stay fixed after the fact, so a quiz has to be versioned together with the pages it tests, using Release 1's immutable snapshots.
2. **Answer keys are an attack surface.** Correct answers must never reach the browser, and a learner must not be able to harvest them by failing repeatedly.

## Solution

Add **campaigns** and **quizzes**.

A campaign is a first-class entity: a name, a description, targets (groups, and — for Administrators — named individuals), an ordered list of modules, optional start and due dates, and a lifecycle `draft → active ⇄ suspended → closed`. A campaign does not copy anything into the Release 1 `assignments` table. Learners' access is derived from it live, against current group membership, exactly as Release 1 derives it from assignments, and ad-hoc direct assignment keeps working unchanged.

Each module in a campaign is `mandatory` or `recommended`. A campaign is complete when every mandatory module is complete — computed on every read, never stored, so it cannot drift after a republish, a deletion, or a membership change. An author can mark a campaign `sequential`, which locks module N until module N−1 is complete; the lock is enforced on the server.

A quiz is a structured block attached to a module draft and frozen into the published version. It supports single-choice, multiple-choice and true/false questions, graded only on the server. When a module has a quiz, completion needs every page viewed, then a pass, then the attestation. A learner who fails chooses to retake only the quiz or to re-read the module first.

Reporting follows Release 1's privacy split: Content Managers get group-level counts and per-question statistics and never a name; Administrators get the full roster.

## User Stories

### Campaign authoring

1. As a Content Manager, I want to create a campaign with a name and description, so that I can group related modules into one programme.
2. As a Content Manager, I want to add modules to a campaign and reorder them, so that learners see the material in the order I intend.
3. As a Content Manager, I want to mark each module in a campaign as mandatory or recommended, so that optional enrichment never blocks completion.
4. As a Content Manager, I want to target a campaign at one or more groups, so that the right teams receive it.
5. As an Administrator, I want to additionally target a campaign at named individuals, so that I can cover people who belong to no suitable group.
6. As a Content Manager, I want to see group names, descriptions and member counts when choosing targets, so that I can pick well without browsing the staff directory.
7. As a Content Manager, I want to set an optional start date and due date, so that the campaign opens and closes on a schedule.
8. As a Content Manager, I want to turn automatic reminders on or off for a campaign, so that I control how much I chase people.
9. As a Content Manager, I want to mark a campaign as sequential, so that foundational modules must be finished before advanced ones unlock.
10. As a Content Manager, I want to keep a campaign in draft while I build it, so that no learner sees or is emailed about half-finished work.
11. As a Content Manager, I want to see which modules in a draft campaign are unpublished or deleted, so that I fix them before activating.
12. As a Content Manager, I want activation to be refused if a mandatory module is not published, so that learners are never handed something unreadable.
13. As a Content Manager, I want to activate a campaign immediately or let its start date activate it, so that I can schedule a launch.
14. As a Content Manager, I want to edit targets and add modules to an active campaign, so that I can adapt a running programme.
15. As a Content Manager, I want a warning, or a block, before I remove a module or a target from an active campaign, so that I do not silently drop people's progress or obligations.
16. As a Content Manager, I want to suspend a campaign, so that its modules disappear from learners' view while I fix a problem.
17. As a Content Manager, I want progress to be kept while a campaign is suspended, so that nobody loses work.
18. As a Content Manager, I want to resume a suspended campaign, so that learners pick up where they left off.
19. As a Content Manager, I want to be prompted for a new due date when I resume a campaign whose due date has passed, so that learners are not instantly overdue.
20. As a Content Manager, I want a visible warning on a resumed campaign until the lapsed due date is reset, so that I do not forget.
21. As a Content Manager, I want to close a campaign, so that it stops sending reminders and accepting new starts while its records remain.
22. As a Content Manager, I want a campaign with recorded progress never to be hard-deleted, so that the evidence of who did what survives.
23. As a Content Manager, I want to delete a draft campaign that never went live, so that abandoned drafts do not pile up.
24. As a Content Manager, I want to see the campaigns I created or collaborate on, so that my list is not cluttered by other people's work.

### Collaboration and permissions

25. As a campaign creator, I want to add other Content Managers as collaborators, so that we can build a campaign together.
26. As a collaborator, I want the same edit and status rights as the creator, so that I am not blocked when the creator is away.
27. As a campaign creator, I want to remove a collaborator, so that I can end their access.
28. As a collaborator, I do not want to be able to add other collaborators or delete the campaign, so that ownership stays with the creator.
29. As an Administrator, I want to see and edit every campaign, so that I can step in when needed.
30. As an Administrator, I want to reassign a campaign whose creator was erased or lost the Content Manager role, so that it is never orphaned.
31. As a Content Manager, I want a campaign I have no part in to behave as if it does not exist, so that I learn nothing about other teams' programmes.
32. As an Administrator, I want every campaign action — create, edit, activate, suspend, resume, close, module added or removed, collaborator changes — audit-logged, so that I can answer who changed what.
33. As a Content Manager, I want to see who else is editing a campaign right now, so that we do not overwrite each other unknowingly.

### Learner experience of campaigns

34. As a learner, I want my campaigns shown on "My learning" with the modules grouped under them, so that I see the whole path.
35. As a learner, I want a progress bar such as "3 of 5 required done", so that I know how far I am.
36. As a learner, I want recommended modules clearly distinguished from required ones, so that I know what I must finish.
37. As a learner, I want locked modules in a sequential campaign to be clearly marked with what unlocks them, so that I understand why I cannot open one.
38. As a learner, I want a locked module to be truly unreachable even by direct URL, so that the order cannot be bypassed.
39. As a learner, I want one email when a campaign is activated for me, so that I know it exists.
40. As a learner, I want the campaign due date and my overdue state shown, so that I can plan.
41. As a learner, I want a suspended campaign to simply disappear from my list, so that I am not confused by something I cannot open.
42. As a learner, I want to keep my progress through a suspension, so that I resume rather than restart.
43. As a learner, I want a module that is also in the open catalog or directly assigned to remain available while a campaign is suspended, so that suspension affects only the campaign.
44. As a learner, I want a campaign to reopen if a module I completed is republished substantively, so that the record stays truthful.
45. As a learner, I want a closed campaign to remain visible as a record, so that I can see what I completed.
46. As a learner who joined a targeted group late, I want the campaign to appear without any action by an author, so that I am not missed.
47. As a learner who left a targeted group, I want to lose the campaign but keep what I completed, so that my record is not erased.

### Reminders

48. As a learner, I want a single reminder per campaign per day listing the mandatory modules I still owe, so that my inbox is not flooded.
49. As a learner, I want reminders never to chase recommended modules, so that optional material is never nagged.
50. As a learner, I want per-module reminders not to duplicate the campaign reminder for the same module on the same day, so that I never get two emails about one thing.
51. As a learner, I want no reminders while a campaign is suspended or closed, so that I am not chased for something I cannot do.
52. As a learner, I want no catch-up burst of emails when a campaign resumes, so that resuming is quiet.
53. As a learner, I want reminder and activation emails in my preferred language, so that I can read them.
54. As an Administrator, I want to trigger a campaign nudge manually, rate-limited to once per campaign per day, so that a double click does not mail everyone twice.

### Quiz authoring

55. As a Content Manager, I want to add a quiz to a module, so that I can require understanding as well as attendance.
56. As a Content Manager, I want to write single-choice, multiple-choice and true/false questions, so that I can test different kinds of knowledge.
57. As a Content Manager, I want to format a question prompt with the same rich-text subset pages use, so that I can include code or emphasis.
58. As a Content Manager, I want to mark the correct answer or answers, so that grading is automatic.
59. As a Content Manager, I want an optional explanation per question, so that learners understand why an answer is right.
60. As a Content Manager, I want to reorder and delete questions, so that I can refine the quiz.
61. As a Content Manager, I want to set a pass mark as a percentage, defaulting to 80%, so that I control how strict it is.
62. As a Content Manager, I want to optionally cap the number of attempts, so that guessing cannot go on forever.
63. As a Content Manager, I want to optionally shuffle questions and answers per attempt, so that learners cannot copy each other's order.
64. As a Content Manager, I want to choose whether correct answers are revealed after a pass, so that I decide how much of the key learners see.
65. As a Content Manager, I want to preview and try the quiz as a learner without recording an attempt, so that I can test it.
66. As a Content Manager, I want a quiz validated before I can publish (at least one question, every question has a correct answer, options are distinct), so that a broken quiz never reaches learners.
67. As a Content Manager, I want the quiz frozen into the version when I publish, so that earlier attempts always refer to the quiz that was actually taken.
68. As a Content Manager, I want to choose `minor` or `substantive` when I add or change a quiz and see how many learners a substantive choice affects first, so that I decide knowingly.
69. As a Content Manager, I want removing a quiz to be a minor change, so that it never forces retakes.
70. As a Content Manager, I want each translation variant to carry its own quiz, so that questions read naturally in each language.
71. As a Content Manager, I want to copy quiz settings from the primary variant when I link a translation, so that I do not retype them.
72. As a Content Manager, I want linking a translation refused when only one of the two variants has a quiz, so that learners are not graded in one language and not the other.
73. As a Content Manager, I want a quiz carried through module duplication, export and import, so that it is not lost in backup or moving content.

### Quiz-taking

74. As a learner, I want the quiz to appear after the last page of a module, so that I take it when I have read the material.
75. As a learner, I want the attestation locked until I have viewed every page and passed the quiz, so that completion means something.
76. As a learner, I want to see my score and whether I passed straight away, so that I know where I stand.
77. As a learner, I want to see which questions I got wrong after a failed attempt, so that I can study them.
78. As a learner, I want correct answers revealed after a pass only if the author allowed it, so that the key stays protected.
79. As a learner, I want to see an explanation for a question when the author wrote one and the key is revealed, so that I learn from mistakes.
80. As a learner who failed, I want to choose between retaking only the quiz and re-reading the module, so that I spend my time sensibly.
81. As a learner retaking only the quiz, I want to skip straight back to the quiz with my page progress intact, so that I am not forced to re-read.
82. As a learner choosing to re-read, I want my page progress cleared so the pages must be viewed again, so that the choice is meaningful.
83. As a learner, I want to be told how many attempts I have left when a cap is set, so that I am not surprised.
84. As a learner who is out of attempts, I want a clear message that an Administrator can reset them, so that I know what to do.
85. As a learner, I want to be able to resume an in-progress quiz attempt after closing the tab, so that I do not lose answers.
86. As a learner who started an attempt before a republish, I want to finish the quiz version I started, so that my attempt is not invalidated mid-way.
87. As a learner, I want to complete the quiz entirely with a keyboard and a screen reader, so that the quiz is accessible.
88. As a learner, I want the quiz to look and feel engaging in light, dark and colour-blind-friendly themes and in English and German, so that assessment is not a chore.
89. As a learner, I want my passing score and the quiz version recorded on my completion, so that the record shows what I passed.
90. As a learner, I want a substantive republish that changes the quiz to ask me to read and pass again, so that my record reflects the current requirement.

### Quiz security

91. As a platform owner, I want correct answers never sent to the browser in any question payload, so that nobody can read the key from the network tab.
92. As a platform owner, I want grading done only on the server, so that a score cannot be forged.
93. As a platform owner, I want a submission checked against the attempt's own question set, so that a learner cannot answer questions they were not asked.
94. As a platform owner, I want attempts to count across translation variants toward a cap, so that switching language cannot reset the count.
95. As an Administrator, I want to reset a learner's attempts, audit-logged, so that I can grant a fair retry.
96. As a platform owner, I want attempt submission rate-limited, so that the key cannot be brute-forced quickly.

### Reporting

97. As a Content Manager, I want a campaign report showing per-group counts — completed, in progress, not started, overdue, suspended — and average progress, so that I see how groups are doing without seeing names.
98. As an Administrator, I want a campaign roster with each learner's state per module, so that I can chase individuals.
99. As an Administrator, I want to export the campaign roster as CSV, so that I can report outside the platform.
100. As a Content Manager, I want the module report to show pass rate, average score and attempts-to-pass per group, so that I can judge whether a module works.
101. As a Content Manager, I want per-question percent-correct, so that I can find confusing or broken questions.
102. As an Administrator, I want each learner's best score and attempt count in the roster and CSV, so that I can evidence results.
103. As a Content Manager, I want never to see a learner's name or individual answers in a report, so that privacy holds.
104. As an Administrator, I want individual answers never exposed through reports, so that they are used only for the learner's own review and audit.

### Privacy and lifecycle

105. As a data subject, I want my per-answer data deleted when my account is erased, so that my right to erasure is honoured.
106. As a Content Manager, I want pass rates and per-question statistics to stay correct after an erase, so that reports do not distort.
107. As an Administrator, I want completion records to survive an erase against the anonymised tombstone, so that proof of training is not lost.
108. As a Content Manager, I want a deleted module to leave a clear marker inside any campaign that listed it, so that nothing breaks silently.

## Implementation Decisions

### Campaigns

- **New entities:** a campaign (name, description, status, `sequential`, start and due dates, `auto_reminders`, creator), campaign modules (campaign, translation group, position, `mandatory`|`recommended`), campaign targets (`user`|`group` with the same non-foreign-key `target_id` pattern as assignments, checked at the route), and campaign collaborators.
- **Modules are referenced by translation group, not module**, consistent with Release 1 assignment, so a translation added later is covered automatically.
- **Access is derived, not expanded.** Targets are stored and resolved against current group membership on every read. A single module-level decision point, extending the existing read-access function, asks "is this module reachable through an *active* campaign, and is it unlocked". Learner routes and asset delivery both continue to ask that one decision.
- **Lifecycle** `draft → active ⇄ suspended → closed`, with an optional start date that activates the campaign through the existing daily job. Closed is terminal.
  - Draft: invisible to learners, no email.
  - Active: visible, one activation email per currently-targeted learner in their preferred language. A learner who joins a group later is not emailed retroactively.
  - Suspended: removes only the campaign's own route to its modules. A module still reachable by a direct assignment or the open catalog stays visible there. A module with no other route returns 404. Progress rows are untouched. Reminders and the `overdue` flag are frozen.
  - Closed: no reminders and no new module starts; existing records stay readable.
- **Activation validation:** refused unless every mandatory module is published and the campaign has at least one target.
- **Resume with a lapsed due date:** resume is allowed, the campaign reports a "due date lapsed" state, and the author is prompted for a new date. Until then the `overdue` flag stays frozen and a warning shows. Due dates never shift automatically.
- **Active-campaign edits:** adding modules and targets is allowed. Removing a module or a target that has learner progress is blocked or requires explicit confirmation showing the affected count, following the "tell the author the number first" pattern of `revision-impact` and `deletion-impact`.
- **Deletion:** a draft campaign that never activated may be hard-deleted by its creator or an Administrator. Any campaign that ever activated is never hard-deleted.
- **Sequencing:** with `sequential` on, module N is locked until N−1 is complete or passed (a SCORM or native module alike). A locked module is a 404 or an explicit locked response to the viewer routes, decided server-side. The viewer API returns lock state and the unlocking prerequisite for the UI to render.
- **Completion:** a campaign is complete when every mandatory module is complete. This is computed live from module progress and never stored. A completion superseded by a substantive republish no longer counts, so the campaign reopens for that learner.
- **Permissions:**
  - Content Managers and Administrators can create campaigns. Content Managers target groups only, and Administrators may also target individuals; an individual target is a 403 for a Content Manager at creation and removal.
  - A Content Manager may edit a campaign only if they created it or are a collaborator; any other campaign is a 404, never a 403, on every route including read.
  - Collaborators have the creator's edit and status rights (activate, suspend, resume, close). Only the creator or an Administrator may add or remove collaborators or delete a draft. Collaborators must hold Content Manager or Administrator; otherwise 409.
  - An Administrator may reassign the creator. If the creator is erased or loses the role, collaborators remain and an Administrator manages ownership.
  - Concurrent-editing presence from Release 1 is reused for campaigns.
  - All campaign mutations are audit-logged.
- **Group listing for Content Managers** reuses the existing counts-only endpoint.

### Reminders and email

- Reminders move to a **campaign level** for campaign-derived obligations: one email per learner per campaign per day listing outstanding *mandatory* modules, on the existing cadence (7 days before, 1 day before, on the due date, weekly while overdue), in the deployment-wide timezone.
- The per-learner daily cap is checked against the send log across both campaign and module reminders; a module's Release 1 reminder is suppressed on a day where the campaign reminder already covers it.
- Suspended and closed campaigns send nothing. Resuming sends no catch-up; the next cadence step applies after any due-date reset.
- The Administrator manual nudge extends to campaigns with the same once-per-day rate limit, checked against its own audit entry as Release 1 does.
- A single `auto_reminders` toggle per campaign governs the lot; there are no per-module reminder overrides.
- The same job entrypoint is used locally and in production. It additionally activates campaigns whose start date has arrived.

### Quizzes

- **Quiz entity** belongs to a module row (one per module), with settings (pass mark default 80, optional attempt cap, shuffle, reveal-after-pass) and ordered questions. A question has a `type` discriminator (`single`, `multiple`, `true_false`), a prompt as a validated ProseMirror document from the existing schema subset, options, the correct set, and an optional explanation.
- **Versioning:** the quiz is snapshotted into the immutable module version on publish, under the existing database-level immutability trigger. Attempts reference the quiz version.
- **Grading** is server-side only. Multiple-choice is all-or-nothing (exact set match). Question payloads sent to learners contain no correctness data. Reveal is gated by the author setting and only after a pass; the explanation is revealed with it.
- **Attempts** are stored with score, timestamp, quiz version, answers given, and a stored shuffle seed so a review reproduces the same order. The best score counts. An attempt is in-progress until submitted and can be resumed. A submission is validated against the attempt's own question set. Submission is rate-limited.
- **Attempt cap** counts across translation variants of the group. An Administrator may reset a learner's attempts; audit-logged.
- **Completion gating:** a module with a quiz requires every page viewed, then a passing attempt, then the attestation, enforced with the same 409 pattern as the existing page-views check. The completion record stores the winning score and the quiz version. A module with no quiz is unchanged.
- **Retake choice after a failure:** *quiz only* keeps page-view progress; *module* clears it. Both are explicit requests to the server.
- **Revisions:** adding or changing a quiz follows the author's `minor` or `substantive` choice. `minor` leaves completions valid; `substantive` supersedes them and clears page views, as now. Removing a quiz is always `minor`. The revision-impact endpoint is extended to count learners affected by a quiz change. A learner mid-attempt finishes the quiz version they started; old attempts do not count toward the new version's cap.
- **Translations:** each variant has its own quiz and settings; "copy from primary" is offered when linking. Linking is a 409 unless both variants have a quiz or neither does. A language switch resets page views as today but keeps attempts and any prior pass.
- **Validation before publish:** at least one question; every question has at least one correct option; single-choice and true/false have exactly one; options distinct and non-empty.
- **Duplicate, export and import** carry the quiz. Imported quizzes pass through the same validators as authored ones, and nothing about the archive's own claims is trusted.

### Reporting

- Campaign report: a Content Manager gets per-targeted-group counts (completed, in progress, not started, overdue, suspended) and average progress, no names. An Administrator gets the per-learner roster with per-module state and a CSV export. Only campaigns the caller may edit are readable by a Content Manager.
- Module report extension: a Content Manager gets pass rate, average score, attempts-to-pass per group and per-question percent-correct. An Administrator additionally gets each learner's best score and attempt count in the roster and CSV. Individual answers are never in any report or CSV.
- No cross-campaign analytics — that is Release 5.

### Privacy

- On user erase, per-answer data is hard-deleted. Attempt rows remain only as de-identified aggregates (score, pass/fail, quiz version, timestamp) pointing at the tombstone, so statistics stay correct. Completion records remain against the tombstone as today.
- Deleting a module that appears in a campaign leaves a marker in the campaign (a module that can no longer be opened); it never silently disappears from the author's view.

### Frontend

- New features under the existing content and learning areas: a campaign list and builder (module ordering, targets, collaborators, state controls, sequential toggle, lapsed-date warning), a quiz editor on the module screen, the quiz-taking experience with results and the retake choice, campaign grouping and progress on "My learning", campaign report panels, and an Administrator nudge button. Quiz-taking and the campaign builder go through `ux-discovery` before tickets are written; everything else reuses Release 1 patterns (panels, publish dialog, report panel, shell navigation).
- All new strings in English and German, all new UI in all three themes, quiz fully keyboard- and screen-reader-operable with focus management and live regions matching the viewer's existing behaviour.

### Infrastructure

- No new AWS services. Campaign reminders and start-date activation run in the existing scheduled task. Terraform needs no new resources; the existing docs are updated to say so.

## Testing Decisions

- **A good test** exercises external behaviour through the highest available seam and asserts on what a caller observes — status codes, response bodies, what a learner can or cannot open, what email was sent, what an audit row says — never on internal helper structure.
- **Backend seam:** the HTTP API against a real Postgres, in the existing `pytest` and `conftest.py` pattern (migrations once per session, rolled-back transaction per test, faked S3, mailer captured as Release 1 does). Cover: the full campaign lifecycle and every illegal transition; suspension visibility including the direct-assignment and catalog fallbacks; sequential locks by direct URL; derived access for late joiners and leavers; the permission matrix including 404-vs-403 and individual-target 403; collaborator add/remove rules and creator reassignment; campaign completion across republish; reminder cadence, the combined daily cap, suppression of duplicate module reminders, and no catch-up on resume; start-date activation through the job entrypoint; quiz authoring validation; that no learner payload contains correctness data; grading for all three types; attempt cap, cross-variant counting, admin reset; resume of an attempt; completion gating order and its 409s; both retake choices; minor versus substantive supersession for add, change and remove of a quiz; mid-attempt republish; translation link refusals; duplicate, export and import carrying the quiz; report shapes per role with no leakage of names or answers to Content Managers; and erase behaviour.
- **Frontend seam:** Vitest and React Testing Library at page and component level, as in the existing features — quiz-taking, retake choice, locked-module rendering, campaign builder, My-learning grouping and progress, report panels, and keyboard operation of the quiz.
- **Prior art:** Release 1's tests for assignments, reminders, reporting, publishing supersession, translation linking, and the learner viewer.
- **Terraform:** `terraform validate` only; no resources are added.

## Out of Scope

- Question types beyond single-choice, multiple-choice and true/false (free text, ordering, matching, fill-in-the-blank, partial credit).
- Dashboards and cross-campaign analytics (Release 5).
- Recurring or annual re-assignment, scheduled publishing, certificates and completion PDFs (deferred list in the roadmap).
- A fully custom permission matrix; roles remain fixed.
- Per-module reminder overrides inside a campaign.
- Automatic due-date shifting after suspension.
- Campaign-level quizzes (a quiz belongs to a module).
- Scoped API tokens.
- SCORM (Release 2.5), including any interplay with platform quizzes.

## Further Notes

- Release 2.5 treats a SCORM module's own pass or completion as the module's completion for campaign completion and sequencing, so Release 2's "complete or passed" check must be written against a single completion notion that SCORM can later feed.
- ROADMAP states that tokens come after Release 2; campaigns and quizzes bring the resource count to the point where scoped API tokens become designable.
- Quiz question and answer text may contain personal opinions or sensitive content authored by humans; it is treated like page content (validated tree, no HTML injection path).
