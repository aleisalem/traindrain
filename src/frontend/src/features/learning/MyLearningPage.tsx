import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { CampaignCard } from "./CampaignCard";
import type { LearnerCampaign, LearnerModuleSummary } from "./types";
import { useLearnerList } from "./useLearnerList";

/**
 * What this learner has started and what they have finished.
 *
 * A module withdrawn since they read it stays on the list: the completion is
 * theirs and does not evaporate because an author retired the material. It
 * simply stops offering a way back in.
 */
export function MyLearningPage() {
  const { t } = useTranslation();
  const state = useLearnerList<LearnerModuleSummary>("/api/me/modules");
  const campaignState = useLearnerList<LearnerCampaign>("/api/me/campaigns");

  if (state.status === "error") {
    return (
      <section className="flex flex-col gap-4">
        <h2 className="text-xl font-semibold">{t("learning.mine_heading")}</h2>
        <p role="alert" className="text-sm text-danger">
          {t("learning.load_error")}
        </p>
      </section>
    );
  }

  if (state.status === "loading" || campaignState.status === "loading") return null;
  // The campaign list is an enhancement over the module list: if only it
  // fails, the learner still sees their modules rather than an error page.
  const campaigns = campaignState.status === "ready" ? campaignState.items : [];
  // A module shown inside a campaign is not listed a second time below.
  const inCampaign = new Set(
    campaigns.flatMap((campaign) => campaign.modules.map((row) => row.translation_group_id)),
  );
  const rows = state.items.filter((row) => !inCampaign.has(row.translation_group_id));

  return (
    <section className="flex flex-col gap-6">
      <div>
        <h2 className="text-xl font-semibold">{t("learning.mine_heading")}</h2>
        <p className="text-sm text-fg-muted">{t("learning.mine_description")}</p>
      </div>

      {campaigns.length > 0 && (
        <section aria-labelledby="my-campaigns-heading" className="flex flex-col gap-3">
          <h3 id="my-campaigns-heading" className="text-lg font-semibold">
            {t("learning.campaigns_heading")}
          </h3>
          <ul className="flex flex-col gap-4">
            {campaigns.map((campaign) => (
              <CampaignCard key={campaign.id} campaign={campaign} />
            ))}
          </ul>
        </section>
      )}

      {campaigns.length > 0 && rows.length > 0 && (
        <h3 className="text-lg font-semibold">{t("learning.other_modules_heading")}</h3>
      )}

      {rows.length === 0 && campaigns.length > 0 ? null : rows.length === 0 ? (
        <div className="flex flex-col items-start gap-3">
          <p className="text-sm text-fg-muted">{t("learning.mine_empty")}</p>
          <Link
            to="/modules/browse"
            className="rounded-full bg-[image:var(--gradient)] px-4 py-1.5 text-sm font-semibold text-primary-fg transition hover:-translate-y-0.5 hover:shadow-[var(--shadow)]"
          >
            {t("learning.mine_empty_cta")}
          </Link>
        </div>
      ) : (
        <ul className="flex flex-col gap-3">
          {rows.map((row) => (
            <li
              key={row.translation_group_id}
              className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-border bg-bg-elevated p-5 shadow-[var(--shadow)]"
            >
              <div className="flex flex-col gap-1">
                <h3 className="text-lg font-medium">{row.title}</h3>
                <p className="text-sm text-fg-muted">
                  {row.completed_at !== null
                    ? t("learning.completed_on", {
                        date: new Date(row.completed_at).toLocaleDateString(),
                        version: row.completed_version_number,
                      })
                    : row.started_at !== null
                      ? t("learning.in_progress")
                      : t("learning.not_started")}
                </p>
                {row.superseded_at !== null && (
                  <p className="text-sm text-warning">{t("learning.superseded")}</p>
                )}
                {(row.due_date !== null || row.requirement !== null) && (
                  <p className={`text-sm ${row.overdue ? "text-danger" : "text-fg-muted"}`}>
                    {row.requirement !== null && t(`learning.requirement_${row.requirement}`)}
                    {row.requirement !== null && row.due_date !== null && " · "}
                    {row.due_date !== null && t("learning.due_on", { date: row.due_date })}
                    {row.overdue && ` · ${t("learning.overdue_badge")}`}
                  </p>
                )}
              </div>
              {row.available ? (
                <Link
                  to={`/modules/${row.translation_group_id}`}
                  className="rounded-full border border-border bg-bg-elevated px-4 py-1.5 text-sm font-medium transition hover:-translate-y-0.5 hover:shadow-[var(--shadow)]"
                >
                  {row.completed_at !== null
                    ? t("learning.open_again")
                    : row.started_at !== null
                      ? t("learning.continue")
                      : t("learning.start")}
                </Link>
              ) : (
                <span className="text-sm text-fg-muted">{t("learning.unavailable_short")}</span>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
