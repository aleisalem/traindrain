import { useTranslation } from "react-i18next";

import type {
  AdministratorCampaignReport,
  CampaignLearnerState,
  CampaignReportModule,
  ContentManagerCampaignReport,
} from "./types";
import type { CampaignReportState } from "./useCampaignReport";

type Props = {
  campaignId: string;
  report: CampaignReportState;
  /** Only an Administrator gets a named roster and the CSV export — the
   *  frontend half of the server's role check in `app.routes.reports`. */
  isAdministrator: boolean;
};

const cardClassName =
  "flex flex-col gap-4 rounded-2xl border border-border bg-bg-elevated p-5 shadow-[var(--shadow)]";

function isGroupSummary(
  report: ContentManagerCampaignReport | AdministratorCampaignReport,
): report is ContentManagerCampaignReport {
  return "groups" in report;
}

function StateBadge({ state }: { state: CampaignLearnerState | "module_unavailable" }) {
  const { t } = useTranslation();
  const tone =
    state === "completed"
      ? "text-success"
      : state === "in_progress"
        ? "text-primary"
        : "text-fg-muted";
  return <span className={`text-xs font-medium ${tone}`}>{t(`campaignReport.state_${state}`)}</span>;
}

function Progress({ percent, label }: { percent: number; label: string }) {
  return (
    <div className="flex items-center gap-2">
      <div
        role="progressbar"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
        className="h-2 w-24 overflow-hidden rounded-full bg-border"
      >
        <div className="h-full bg-primary" style={{ width: `${percent}%` }} />
      </div>
      <span className="text-xs text-fg-muted">{percent}%</span>
    </div>
  );
}

/**
 * Did people do this programme? Two renderings behind one fetch — the server,
 * not this component, decided which shape came back.
 */
export function CampaignReportPanel({ campaignId, report, isAdministrator }: Props) {
  const { t } = useTranslation();

  if (report.loadError) {
    return (
      <section className={cardClassName}>
        <h3 className="text-lg font-medium">{t("campaignReport.heading")}</h3>
        <p role="alert" className="text-sm text-danger">
          {t("campaignReport.load_error")}
        </p>
      </section>
    );
  }
  if (report.loading || report.report === null) return null;

  return (
    <section className={cardClassName} aria-labelledby="campaign-report-heading">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 id="campaign-report-heading" className="text-lg font-medium">
            {t("campaignReport.heading")}
          </h3>
          <p className="text-sm text-fg-muted">{t("campaignReport.description")}</p>
        </div>
        {isAdministrator && (
          <a
            href={`/api/content/campaigns/${campaignId}/report.csv`}
            className="shrink-0 rounded-full border border-border px-4 py-2 text-xs font-medium transition hover:-translate-y-0.5"
          >
            {t("campaignReport.export_csv")}
          </a>
        )}
      </div>
      {report.report.status === "suspended" && (
        <p role="status" className="text-sm text-fg-muted">
          {t("campaignReport.suspended_note")}
        </p>
      )}
      {isGroupSummary(report.report) ? (
        <GroupTable report={report.report} />
      ) : (
        <Roster report={report.report} />
      )}
    </section>
  );
}

function GroupTable({ report }: { report: ContentManagerCampaignReport }) {
  const { t } = useTranslation();
  if (report.groups.length === 0) {
    return <p className="text-sm text-fg-muted">{t("campaignReport.empty")}</p>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[40rem] text-left text-sm">
        <thead>
          <tr className="border-b border-border text-xs uppercase tracking-wide text-fg-muted">
            <th className="py-2 pr-4">{t("report.column_group")}</th>
            <th className="py-2 pr-4">{t("report.column_completed")}</th>
            <th className="py-2 pr-4">{t("report.column_in_progress")}</th>
            <th className="py-2 pr-4">{t("report.column_not_started")}</th>
            <th className="py-2 pr-4">{t("report.column_overdue")}</th>
            <th className="py-2 pr-4">{t("campaignReport.column_suspended")}</th>
            <th className="py-2 pr-4">{t("campaignReport.column_average")}</th>
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
              <td className="py-2 pr-4">{group.suspended}</td>
              <td className="py-2 pr-4">
                <Progress
                  percent={group.average_progress}
                  label={t("campaignReport.average_label", { name: group.group_name })}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function moduleHeading(module: CampaignReportModule, fallback: string): string {
  return module.title ?? fallback;
}

function Roster({ report }: { report: AdministratorCampaignReport }) {
  const { t } = useTranslation();
  if (report.learners.length === 0) {
    return <p className="text-sm text-fg-muted">{t("campaignReport.empty")}</p>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[48rem] text-left text-sm">
        <thead>
          <tr className="border-b border-border text-xs uppercase tracking-wide text-fg-muted">
            <th className="py-2 pr-4">{t("report.column_name")}</th>
            <th className="py-2 pr-4">{t("report.column_email")}</th>
            <th className="py-2 pr-4">{t("report.column_status")}</th>
            <th className="py-2 pr-4">{t("campaignReport.column_progress")}</th>
            {report.modules.map((module) => (
              <th key={module.translation_group_id} className="py-2 pr-4">
                {moduleHeading(module, t("campaignReport.untitled_module"))}
                <span className="block text-[0.65rem] normal-case text-fg-muted">
                  {t(`campaignReport.requirement_${module.requirement}`)}
                </span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {report.learners.map((learner) => (
            <tr key={learner.user_id} className="border-b border-border last:border-0">
              <td className="py-2 pr-4 font-medium">{learner.name}</td>
              <td className="py-2 pr-4">{learner.email}</td>
              <td className="py-2 pr-4">
                <StateBadge state={learner.state} />
                {learner.overdue && (
                  <span className="ml-2 text-xs font-medium text-danger">
                    {t("report.overdue_flag")}
                  </span>
                )}
              </td>
              <td className="py-2 pr-4">
                <Progress
                  percent={learner.progress_percent}
                  label={t("campaignReport.average_label", { name: learner.name })}
                />
                <span className="text-xs text-fg-muted">
                  {t("campaignReport.required_done", {
                    done: learner.required_done,
                    total: learner.required_total,
                  })}
                </span>
              </td>
              {learner.modules.map((cell) => (
                <td key={cell.translation_group_id} className="py-2 pr-4">
                  {cell.unavailable ? (
                    <StateBadge state="module_unavailable" />
                  ) : (
                    <StateBadge state={cell.state} />
                  )}
                  {cell.state !== "completed" && cell.completed_at && (
                    <span className="block text-xs text-fg-muted">
                      {t("campaignReport.previously_completed", {
                        version: cell.completed_version_number ?? "?",
                      })}
                    </span>
                  )}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
