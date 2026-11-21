import { useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  AdministratorModuleReport,
  ContentManagerModuleReport,
  LearnerState,
} from "./types";
import { QuizReportSection } from "./QuizReportSection";
import type { ModuleReportState } from "./useModuleReport";

type Props = {
  moduleId: string;
  report: ModuleReportState;
  /** Only an Administrator gets a named roster and the CSV export — the
   *  frontend half of the server's role check in `app.routes.reports`. */
  isAdministrator: boolean;
};

const cardClassName =
  "flex flex-col gap-4 rounded-2xl border border-border bg-bg-elevated p-5 shadow-[var(--shadow)]";

function isGroupSummary(
  report: ContentManagerModuleReport | AdministratorModuleReport,
): report is ContentManagerModuleReport {
  return "groups" in report;
}

function StateBadge({ state }: { state: LearnerState }) {
  const { t } = useTranslation();
  const toneClassName =
    state === "completed"
      ? "text-success"
      : state === "in_progress"
        ? "text-primary"
        : "text-fg-muted";
  return (
    <span className={`text-xs font-medium ${toneClassName}`}>
      {t(`report.state_${state}`)}
    </span>
  );
}

/**
 * Did this module's material land? Two different renderings behind one fetch
 * (`useModuleReport`) — the server, not this component, decided which shape
 * came back, so the branch here is purely presentational.
 */
export function ModuleReportPanel({ moduleId, report, isAdministrator }: Props) {
  const { t } = useTranslation();

  if (report.loadError) {
    return (
      <section className={cardClassName}>
        <h3 className="text-lg font-medium">{t("report.heading")}</h3>
        <p role="alert" className="text-sm text-danger">
          {t("report.load_error")}
        </p>
      </section>
    );
  }

  if (report.loading || report.report === null) return null;

  return (
    <section className={cardClassName}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-lg font-medium">{t("report.heading")}</h3>
          <p className="text-sm text-fg-muted">{t("report.description")}</p>
        </div>
        {isAdministrator && (
          <a
            href={`/api/content/modules/${moduleId}/report.csv`}
            className="shrink-0 rounded-full border border-border px-4 py-2 text-xs font-medium transition hover:-translate-y-0.5"
          >
            {t("report.export_csv")}
          </a>
        )}
      </div>

      {isGroupSummary(report.report) ? (
        <GroupSummaryTable report={report.report} />
      ) : (
        <RosterTable report={report.report} moduleId={moduleId} />
      )}

      {report.report.quiz && (
        <QuizReportSection
          quiz={report.report.quiz}
          groups={isGroupSummary(report.report) ? report.report.groups : []}
        />
      )}
    </section>
  );
}

function GroupSummaryTable({ report }: { report: ContentManagerModuleReport }) {
  const { t } = useTranslation();

  if (report.groups.length === 0) {
    return <p className="text-sm text-fg-muted">{t("report.empty")}</p>;
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[36rem] text-left text-sm">
        <thead>
          <tr className="border-b border-border text-xs uppercase tracking-wide text-fg-muted">
            <th className="py-2 pr-4">{t("report.column_group")}</th>
            <th className="py-2 pr-4">{t("report.column_completed")}</th>
            <th className="py-2 pr-4">{t("report.column_in_progress")}</th>
            <th className="py-2 pr-4">{t("report.column_not_started")}</th>
            <th className="py-2 pr-4">{t("report.column_overdue")}</th>
          </tr>
        </thead>
        <tbody>
          {report.groups.map((group) => (
            <tr key={group.group_id} className="border-b border-border last:border-0">
              <td className="py-2 pr-4 font-medium">
                {group.group_name}{" "}
                <span className="text-xs text-fg-muted">
                  ({t("report.member_count", { count: group.member_count })})
                </span>
              </td>
              <td className="py-2 pr-4">{group.completed}</td>
              <td className="py-2 pr-4">{group.in_progress}</td>
              <td className="py-2 pr-4">{group.not_started}</td>
              <td className="py-2 pr-4">{group.overdue}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * Gives one learner a clean slate on this module's quiz. Two clicks, because
 * it deletes attempts for good; the outcome is announced in a live region.
 */
function ResetAttemptsControl({
  moduleId,
  userId,
  name,
}: {
  moduleId: string;
  userId: string;
  name: string;
}) {
  const { t } = useTranslation();
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<{ ok: boolean; deleted: number } | null>(null);

  async function reset() {
    setBusy(true);
    try {
      const response = await fetch(`/api/content/modules/${moduleId}/quiz/attempts/reset`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: userId }),
      });
      const body = response.ok ? await response.json() : null;
      setOutcome({ ok: response.ok, deleted: body?.attempts_deleted ?? 0 });
    } catch {
      setOutcome({ ok: false, deleted: 0 });
    } finally {
      setBusy(false);
      setConfirming(false);
    }
  }

  return (
    <div className="flex flex-col items-start gap-1">
      {confirming ? (
        <span className="flex gap-2">
          <button
            type="button"
            disabled={busy}
            onClick={() => void reset()}
            className="rounded-full bg-danger px-3 py-1 text-xs font-medium text-white disabled:opacity-60"
          >
            {t("report.reset_attempts_confirm", { name })}
          </button>
          <button
            type="button"
            onClick={() => setConfirming(false)}
            className="rounded-full border border-border px-3 py-1 text-xs font-medium"
          >
            {t("report.reset_attempts_cancel")}
          </button>
        </span>
      ) : (
        <button
          type="button"
          onClick={() => {
            setOutcome(null);
            setConfirming(true);
          }}
          className="rounded-full border border-border px-3 py-1 text-xs font-medium transition hover:-translate-y-0.5"
        >
          {t("report.reset_attempts", { name })}
        </button>
      )}
      <span role="status" className="text-xs text-fg-muted">
        {outcome === null
          ? ""
          : outcome.ok
            ? t("report.reset_attempts_done", { count: outcome.deleted })
            : t("report.reset_attempts_error")}
      </span>
    </div>
  );
}

function RosterTable({
  report,
  moduleId,
}: {
  report: AdministratorModuleReport;
  moduleId: string;
}) {
  const { t } = useTranslation();

  if (report.learners.length === 0) {
    return <p className="text-sm text-fg-muted">{t("report.empty")}</p>;
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[52rem] text-left text-sm">
        <thead>
          <tr className="border-b border-border text-xs uppercase tracking-wide text-fg-muted">
            <th className="py-2 pr-4">{t("report.column_name")}</th>
            <th className="py-2 pr-4">{t("report.column_email")}</th>
            <th className="py-2 pr-4">{t("report.column_status")}</th>
            <th className="py-2 pr-4">{t("report.column_completed_version")}</th>
            <th className="py-2 pr-4">{t("report.column_due_date")}</th>
            {report.quiz && (
              <>
                <th className="py-2 pr-4">{t("report.column_best_score")}</th>
                <th className="py-2 pr-4">{t("report.column_attempt_count")}</th>
              </>
            )}
            <th className="py-2 pr-4">{t("report.column_quiz")}</th>
          </tr>
        </thead>
        <tbody>
          {report.learners.map((learner) => (
            <tr key={learner.user_id} className="border-b border-border last:border-0">
              <td className="py-2 pr-4 font-medium">{learner.name}</td>
              <td className="py-2 pr-4 text-fg-muted">{learner.email}</td>
              <td className="py-2 pr-4">
                <StateBadge state={learner.state} />
                {learner.overdue && (
                  <span className="ml-2 text-xs text-danger">{t("report.overdue_flag")}</span>
                )}
              </td>
              <td className="py-2 pr-4">
                {learner.completed_version_number
                  ? t("report.version_number", { number: learner.completed_version_number })
                  : "—"}
              </td>
              <td className="py-2 pr-4">
                {learner.due_date ? learner.due_date : t("report.no_due_date")}
              </td>
              {report.quiz && (
                <>
                  <td className="py-2 pr-4">
                    {learner.best_score_percent == null ? "—" : `${learner.best_score_percent}%`}
                  </td>
                  <td className="py-2 pr-4">{learner.attempt_count ?? 0}</td>
                </>
              )}
              <td className="py-2 pr-4">
                <ResetAttemptsControl
                  moduleId={moduleId}
                  userId={learner.user_id}
                  name={learner.name}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
