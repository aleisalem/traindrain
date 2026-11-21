# Release 2 security review

Static review (`security-scan`) of the release's changes against `main`, focused on the new attack
surface: campaign routes, quiz authoring/taking/grading, reports and CSV, erase handling.

**Result: no high-confidence (≥ 0.8) vulnerabilities found.**

Checked and found sound:

- **Authorization**: every campaign route resolves visibility through one check (`may_see_campaign`)
  and returns 404 to non-participants; collaborator management, draft deletion, owner reassignment,
  individual targets, manual nudges, attempt resets and every CSV export are Administrator/creator-only
  at the route-dependency level, not inside shared handlers.
- **No answer leakage**: learner quiz payloads carry question text and options only; correctness is
  revealed only as per-question right/wrong after a submit, and the key/explanations only after a pass
  when the author allowed it. Quiz reports read `score`, `passed` and `question_results` and never
  select `QuizAttempt.answers`. Covered by tests.
- **IDOR / forgery**: attempts are loaded by id *and* owner *and* translation group; answers are
  validated against the attempt's own frozen version, so forged or foreign question/option ids are 404/422.
- **Injection**: quiz prompts and explanations go through the ProseMirror validator (rejected, never
  stripped), including on import; all queries use the ORM; CSV text cells are neutralised against
  formula injection.
- **Privacy**: Content Manager reports contain counts only; individually-targeted learners are excluded
  from group aggregates; an erase hard-deletes answers and keeps only de-identified aggregates.

Observations (not vulnerabilities, accepted by design):

- After a failed attempt the learner learns which questions were wrong (a ticket requirement); the
  attempt cap and submission rate limit bound how much that can be probed. Note the per-question
  right/wrong flags let a learner with an unlimited cap converge on the key — authors who need more
  should set a cap.
- Module-report CSV cells for name/email predate this release and are not formula-neutralised
  (the campaign CSV is). Low severity; Administrator-only export.
