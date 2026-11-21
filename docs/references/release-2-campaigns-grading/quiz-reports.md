# Quiz reports

The module report (`GET /api/content/modules/{id}/report`) gains a quiz section whenever the module
has a published quiz; modules without one are unchanged (`quiz: null`). Same privacy split as the rest
of the report, decided on the server.

- **Content Manager**: per targeted group — learners who attempted, passed, pass rate, average score,
  and average attempts-to-pass — plus a module-wide `quiz` block with per-question percent-correct for
  the current published quiz (question text, answered, correct, %). Never a name, email or answer.
- **Administrator**: the same, plus each learner's best score and attempt count in the roster
  (`best_score_percent`, `attempt_count`) and as `Best Quiz Score %` / `Quiz Attempts` columns in
  `GET .../report.csv` (present only when the module has a quiz).
- **No individual answers anywhere.** `app.quiz_reporting` never selects `QuizAttempt.answers`; it reads
  only score, pass/fail, version and the per-question right/wrong flags.
- **Erase**: those columns survive a user erase (answers are what is hard-deleted), so the module-wide
  `overall` figures and per-question percentages are unchanged afterwards. Per-group figures follow live
  membership like every other report count, so an erased learner stops appearing in a group.
- Definitions: pass rate = learners who ever passed ÷ learners who attempted; attempts-to-pass = which
  submitted attempt first passed, averaged over those who passed; per-question figures use attempts on
  the current published version only, so a republished quiz starts its question statistics afresh.
- Code: `app.quiz_reporting`, `app.routes.reports`, `app.schemas.reports`. Frontend:
  `QuizReportSection.tsx` inside `ModuleReportPanel.tsx`.
