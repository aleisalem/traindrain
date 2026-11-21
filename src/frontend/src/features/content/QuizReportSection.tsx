import { useTranslation } from "react-i18next";

import type { ModuleReportGroupSummary, QuizReport } from "./types";

const dash = "—";

function percent(value: number | null | undefined): string {
  return value === null || value === undefined ? dash : `${value}%`;
}

/**
 * The quiz half of a module report: how the learners fared per group and how
 * each question fared overall. Statistics only — the server never sends an
 * individual answer, so there is nothing here to hide.
 */
export function QuizReportSection({
  quiz,
  groups,
}: {
  quiz: QuizReport;
  groups: ModuleReportGroupSummary[];
}) {
  const { t } = useTranslation();
  const groupRows = groups.filter((group) => group.quiz);

  return (
    <section aria-labelledby="quiz-report-heading" className="flex flex-col gap-4 border-t border-border pt-4">
      <div>
        <h4 id="quiz-report-heading" className="text-base font-medium">
          {t("report.quiz_heading")}
        </h4>
        <p className="text-sm text-fg-muted">
          {t("report.quiz_description", { mark: quiz.pass_mark_percent, attempts: quiz.attempts })}
        </p>
        <p className="text-sm">
          {t("report.quiz_overall", {
            attempted: quiz.overall.attempted,
            passed: quiz.overall.passed,
            rate: percent(quiz.overall.pass_rate_percent),
          })}
        </p>
      </div>

      {groupRows.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[36rem] text-left text-sm">
            <caption className="sr-only">{t("report.quiz_group_heading")}</caption>
            <thead>
              <tr className="border-b border-border text-xs uppercase tracking-wide text-fg-muted">
                <th scope="col" className="py-2 pr-4">{t("report.column_group")}</th>
                <th scope="col" className="py-2 pr-4">{t("report.column_attempted")}</th>
                <th scope="col" className="py-2 pr-4">{t("report.column_passed")}</th>
                <th scope="col" className="py-2 pr-4">{t("report.column_pass_rate")}</th>
                <th scope="col" className="py-2 pr-4">{t("report.column_avg_score")}</th>
                <th scope="col" className="py-2 pr-4">{t("report.column_avg_attempts")}</th>
              </tr>
            </thead>
            <tbody>
              {groupRows.map((group) => (
                <tr key={group.group_id} className="border-b border-border last:border-0">
                  <th scope="row" className="py-2 pr-4 font-medium">{group.group_name}</th>
                  <td className="py-2 pr-4">{group.quiz!.attempted}</td>
                  <td className="py-2 pr-4">{group.quiz!.passed}</td>
                  <td className="py-2 pr-4">{percent(group.quiz!.pass_rate_percent)}</td>
                  <td className="py-2 pr-4">{percent(group.quiz!.average_score_percent)}</td>
                  <td className="py-2 pr-4">{group.quiz!.average_attempts_to_pass ?? dash}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div>
        <h5 className="text-sm font-medium">{t("report.quiz_questions_heading")}</h5>
        <p className="mb-2 text-xs text-fg-muted">{t("report.quiz_questions_hint")}</p>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[28rem] text-left text-sm">
            <caption className="sr-only">{t("report.quiz_questions_heading")}</caption>
            <thead>
              <tr className="border-b border-border text-xs uppercase tracking-wide text-fg-muted">
                <th scope="col" className="py-2 pr-4">{t("report.column_question")}</th>
                <th scope="col" className="py-2 pr-4">{t("report.column_answered")}</th>
                <th scope="col" className="py-2 pr-4">{t("report.column_percent_correct")}</th>
              </tr>
            </thead>
            <tbody>
              {quiz.questions.map((question) => (
                <tr key={question.question_id} className="border-b border-border last:border-0">
                  <th scope="row" className="py-2 pr-4 font-normal">{question.prompt_text}</th>
                  <td className="py-2 pr-4">{question.answered}</td>
                  <td className="py-2 pr-4">
                    {question.percent_correct === null ? (
                      dash
                    ) : (
                      <span className="flex items-center gap-2">
                        <span
                          aria-hidden="true"
                          className="h-2 w-24 overflow-hidden rounded-full bg-border"
                        >
                          <span
                            className="block h-full bg-primary"
                            style={{ width: `${question.percent_correct}%` }}
                          />
                        </span>
                        {question.percent_correct}%
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}
