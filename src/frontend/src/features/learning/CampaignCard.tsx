import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import type { LearnerCampaign } from "./types";

/**
 * One campaign on "my learning": a progress bar over its required modules, and
 * its modules in the author's order with mandatory told apart from recommended.
 *
 * Everything shown was computed by the server on this read, so a substantive
 * republish that reopened a finished campaign simply arrives as fewer required
 * modules done. Status is never conveyed by colour alone — every state also
 * has a text label.
 */
export function CampaignCard({ campaign }: { campaign: LearnerCampaign }) {
  const { t } = useTranslation();
  const percent =
    campaign.required_total === 0
      ? 0
      : Math.round((campaign.required_done / campaign.required_total) * 100);
  const progressLabel = t("learning.campaign_progress", {
    done: campaign.required_done,
    total: campaign.required_total,
  });

  return (
    <li className="flex flex-col gap-4 rounded-2xl border border-border bg-bg-elevated p-5 shadow-[var(--shadow)]">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex flex-col gap-1">
          <h3 className="text-lg font-semibold">{campaign.name}</h3>
          {campaign.description && (
            <p className="text-sm text-fg-muted">{campaign.description}</p>
          )}
        </div>
        <div className="flex flex-wrap gap-2 text-xs font-semibold">
          {campaign.complete && (
            <span className="rounded-full border border-border px-2.5 py-0.5">
              {t("learning.campaign_complete")}
            </span>
          )}
          {campaign.status === "closed" && (
            <span className="rounded-full border border-border px-2.5 py-0.5 text-fg-muted">
              {t("learning.campaign_closed")}
            </span>
          )}
          {campaign.overdue && (
            <span className="rounded-full border border-danger px-2.5 py-0.5 text-danger">
              {t("learning.campaign_overdue")}
            </span>
          )}
        </div>
      </div>

      {campaign.due_date !== null && (
        <p className={`text-sm ${campaign.overdue ? "text-danger" : "text-fg-muted"}`}>
          {t("learning.due_on", { date: campaign.due_date })}
        </p>
      )}

      {campaign.required_total > 0 ? (
        <div className="flex flex-col gap-1">
          <div
            role="progressbar"
            aria-label={progressLabel}
            aria-valuemin={0}
            aria-valuemax={campaign.required_total}
            aria-valuenow={campaign.required_done}
            className="h-2.5 w-full overflow-hidden rounded-full bg-border"
          >
            <div
              className="h-full rounded-full bg-[image:var(--gradient)] transition-all"
              style={{ width: `${percent}%` }}
            />
          </div>
          <p className="text-sm text-fg-muted">{progressLabel}</p>
        </div>
      ) : (
        <p className="text-sm text-fg-muted">{t("learning.campaign_no_required")}</p>
      )}

      <ol className="flex flex-col gap-2">
        {campaign.modules.map((row) => (
          <li
            key={row.translation_group_id}
            className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border px-4 py-3"
          >
            <div className="flex flex-col gap-0.5">
              <span className="font-medium">{row.title}</span>
              <span className={`text-sm ${row.overdue ? "text-danger" : "text-fg-muted"}`}>
                {t(`learning.requirement_${row.requirement}`)}
                {" · "}
                {t(`learning.module_state_${row.state}`)}
                {row.overdue && ` · ${t("learning.overdue_badge")}`}
              </span>
            </div>
            {row.available ? (
              <Link
                to={`/modules/${row.translation_group_id}`}
                className="rounded-full border border-border bg-bg-elevated px-4 py-1.5 text-sm font-medium transition hover:-translate-y-0.5 hover:shadow-[var(--shadow)]"
              >
                {row.state === "completed"
                  ? t("learning.open_again")
                  : row.state === "in_progress"
                    ? t("learning.continue")
                    : t("learning.start")}
              </Link>
            ) : (
              <span className="text-sm text-fg-muted">{t("learning.unavailable_short")}</span>
            )}
          </li>
        ))}
      </ol>
    </li>
  );
}
