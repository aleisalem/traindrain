# Attempt administration and erase

- **Reset**: `POST /api/content/modules/{id}/quiz/attempts/reset` with `{user_id}`; Administrator only
  (403 otherwise, 404 for an unknown module or user). Deletes every quiz attempt the learner has on the
  module's translation group, open or submitted, and returns `attempts_deleted`. Audited as
  `quiz_attempts_reset` with the module and learner. `module_progress` (the completion record) is not touched.
- **Cap across translations**: attempts, the best score and "any prior pass" are counted over the current
  version of every language variant of the material (`app.quiz_attempts.group_version_ids`). A republish of
  a variant still drops that variant's old attempts from the count; switching language does not.
- **Erase**: `POST /api/admin/users/{id}/erase` calls `deidentify_attempts`: attempts in progress are
  deleted, submitted ones lose `answers` (and shuffle seed) but keep score, pass/fail, version, timestamp and
  per-question right/wrong flags against the anonymous tombstone user. `attempt_aggregates` counts them, so
  figures are unchanged by an erase.
- **Frontend**: a two-step "Reset attempts" button per learner in the Administrator roster; the learner's
  exhausted-attempts message already tells them to ask an Administrator.
- **Roster reach**: the Administrator roster (and CSV) also lists learners who have quiz attempts on the
  material but are named by no assignment (e.g. catalog readers), so they can be reset.
