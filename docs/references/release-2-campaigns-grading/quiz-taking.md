# Quiz-taking, grading and completion gating

Release 2, ticket 9. A learner reaches the quiz after the last page of a module, answers it, and sees their result at once. The server grades everything.

## Storage

Migration `a3e7c1d9f2b4` adds `quiz_attempts` (learner, translation group, variant, the **version** whose quiz was taken, its number, a stored `shuffle_seed`, `answers` as question id → option ids, and — once submitted — score, counts, `passed` and a per-question right/wrong map) and two columns on `module_progress`: `completed_score_percent` and `completed_quiz_version_number`. A partial unique index allows at most one open attempt per learner and material, which is what makes resume unambiguous.

## API (learner; all under `/api/me/modules/{translation_group_id}/quiz`)

- `GET` — the open attempt, else the latest result, plus a summary (pass mark, cap, attempts used/remaining, `passed`).
- `POST /attempts` — start, or resume the open attempt (even one on an earlier version).
- `PUT /attempts/{id}/answers/{question_id}` — save one answer as it is chosen; validated against the attempt's own question set (foreign question → 404, foreign/too many options → 422).
- `POST /attempts/{id}/submit` — grades the stored answers; rate-limited to 5 submissions per learner per 10 minutes (429).
- `POST /retake` with `{"mode": "quiz" | "module"}` — only after a failed attempt (else 409): `quiz` starts a fresh attempt keeping `pages_viewed`; `module` clears `pages_viewed`.

`GET /api/me/modules/{id}` also carries a `quiz` summary (counts and settings only — never questions).

## Rules

- **No correctness data in payloads.** Options are an id and text. After a submission the learner sees a right/wrong flag per question; the correct options and explanations (`revealed`) are sent only after a pass and only if the author enabled `reveal_after_pass`.
- Single-choice and true/false match the one correct option; multiple-choice is all-or-nothing on the exact set (`app.quiz.grade`).
- **Cap** counts attempts against the version being read, so a republish starts the count afresh; at the cap, starting is 409 `attempts_exhausted`. A learner who has passed cannot start another attempt (409 `quiz_already_passed`).
- **Gating**: starting needs every page viewed (409 `pages_outstanding`); `POST .../complete` needs pages, then a counting pass (409 `quiz_not_passed`), then records the winning score and quiz version. A pass counts if it was taken on the current version or on an earlier one whose quiz is identical in content — so a minor republish does not force a retake, while a changed quiz does. Modules without a quiz behave as before.
- **Mid-attempt republish**: the attempt keeps its own version's questions and can be finished; new attempts use the new version.
- Attempt ids are the learner's own: another learner's id is a 404.

## Frontend

`src/frontend/src/features/learning/QuizPanel.tsx` (+ `useQuizAttempt.ts`), rendered by `ModuleViewerPage.tsx` above the attestation, which stays disabled until the quiz is passed. One question per screen with a progress bar, answers saved on selection, focus moved to the question/result heading, position and outcome announced through a live region, wrong answers marked with an icon and words (not colour alone), a confetti burst on a pass that is disabled under `prefers-reduced-motion`, and a retake choice (quiz only / re-read module) after a failure. Strings are in the `quiz_taking` namespace (EN/DE).

Out of scope here: cross-variant attempt counting and administrator reset (ticket 11).
