# Quizzes across translations, duplicate, export and import

Release 2, ticket 10.

- **Per variant.** A quiz belongs to a module row, so each language variant authors its own.
- **Link refusal.** `POST /api/content/translation-groups/{id}/variants` returns 409
  `quiz_presence_mismatch` unless the module being linked and the group's variants either all have a
  draft quiz or none do. The body names `lacking_side` (`source` or `group`), `lacking_module_id`
  and `lacking_language`.
- **Copy from primary.** `POST /api/content/modules/{id}/quiz/copy-from-primary`
  (`{include_questions: bool}`) copies pass mark, attempt cap, shuffle and reveal settings from the
  group's primary variant, creating the quiz if absent. With `include_questions` the variant's
  questions are replaced by copies with fresh ids. 409 `is_primary_variant` / `primary_has_no_quiz`
  otherwise. Audited as `quiz_updated` (`change: copied_from_primary`).
- **Duplicate** copies the draft quiz; the copy is fully independent.
- **Export** adds an optional `quiz` object to `module.json` (settings and questions, no ids or
  verdicts). Older archives without it still import.
- **Import** builds the quiz from the same request models authoring uses (field limits, question
  types) and validates every prompt and explanation with the page-body validator before anything is
  created; any rejection leaves nothing behind. The manifest cannot claim a quiz is valid — the
  publish gate still decides.

Code: `app/quiz.py` (`clone_draft_quiz`, `add_question_rows`), `app/routes/quiz.py`,
`app/routes/transfer.py`, `app/routes/content.py`, `app/schemas/transfer.py`.
