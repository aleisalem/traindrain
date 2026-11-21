# Quiz authoring and snapshotting

Release 2, ticket 8. A Content Manager adds a quiz to a module draft; publishing validates it and freezes it into the immutable version.

## Storage

Migration `f1d6a8c3b9e4` adds `module_quizzes` (one per module row: `pass_mark_percent` default 80, optional `max_attempts`, `shuffle`, `reveal_after_pass`), `quiz_questions` (a `type` discriminator — `single_choice`, `multiple_choice`, `true_false` — a rich-text `prompt`, optional `explanation`) and `quiz_options` (plain text + `is_correct`). Only the **draft** lives in these tables. The published quiz is frozen into `module_versions.snapshot["quiz"]` (null for a module without one), so the existing `BEFORE UPDATE` trigger already makes it immutable. A true/false question stores the literal options `"true"`/`"false"`; the UI localizes the labels.

Prompts and explanations go through the same server-side ProseMirror validator as page bodies (`validate_page_body`): rejected with 422, never stripped.

## API (Content Manager / Administrator)

- `GET /api/content/modules/{id}/quiz` — the draft with correct answers and a `problems` list (what would block publishing), or `null`.
- `PUT .../quiz` — create the quiz or replace its settings; `DELETE .../quiz` removes it.
- `POST .../quiz/questions`, `PATCH|DELETE .../quiz/questions/{qid}` (a PATCH's `options` replaces the list), `POST .../quiz/questions/reorder`.
- `POST .../quiz/tryout` — grades the author's answers server-side against the draft and records nothing (no attempt, progress, or audit entry).

Correct answers are only ever returned on these author routes; learner routes read named fields from the snapshot and never serialize the quiz.

## Publishing

`app/quiz.py:quiz_problems` is the publish gate: at least one question; non-empty prompt; for single/multiple choice at least two distinct (case-insensitive), non-empty options; exactly one correct answer for single-choice and true/false, at least one for multiple-choice; true/false offers exactly True and False. A failing quiz makes `POST .../publish` a 422 `invalid_quiz` listing the problems, and no version is written.

`GET .../revision-impact` gains `quiz_change` (`none` | `added` | `changed` | `removed`, comparing the draft to the last published version on content, not ids) and `quiz_affected_learners` (the completed learners a substantive publish would supersede when a quiz is added or changed; always 0 for a removal). Removing a quiz is always minor: nobody has anything new to sit.

`app/quiz.py:grade` is the one place answers become a score (exact set match per question; shared with ticket 9).

Audit: `quiz_updated` (with a `change` of `created`, `settings_updated`, `question_added`, `question_updated`, `question_removed`, `questions_reordered`, `removed`), and `module_published` additionally records `quiz_change` and `quiz_question_count`. Deleting a module (a tombstone) also deletes its draft quiz.

## Frontend

`ModuleQuizPanel.tsx` on the module screen (settings, per-question editor with the Tiptap editor for prompt/explanation, localized publish blockers, `QuizTryout.tsx`), `useModuleQuiz.ts`, and a note on quiz changes in `PublishDialog.tsx`. EN/DE, all themes.
