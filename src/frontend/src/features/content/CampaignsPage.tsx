import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import type { CampaignSummary } from "./types";

/** The campaigns the caller may see — the server decides which, so this page
 *  never filters by author itself. */
export function CampaignsPage() {
  const { t } = useTranslation();
  const [campaigns, setCampaigns] = useState<CampaignSummary[] | null>(null);
  const [loadError, setLoadError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const response = await fetch("/api/content/campaigns");
        if (cancelled) return;
        if (!response.ok) {
          setLoadError(true);
          return;
        }
        setCampaigns(await response.json());
      } catch {
        if (!cancelled) setLoadError(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <section className="flex flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold">{t("campaigns.heading")}</h2>
          <p className="text-sm text-fg-muted">{t("campaigns.description")}</p>
        </div>
        <Link
          to="/content/campaigns/new"
          className="rounded-full bg-[image:var(--gradient)] px-5 py-2.5 text-sm font-semibold text-primary-fg transition hover:-translate-y-0.5 hover:shadow-[var(--shadow)]"
        >
          {t("campaigns.new_campaign")}
        </Link>
      </div>

      {loadError && (
        <p role="alert" className="text-sm text-danger">
          {t("campaigns.load_error")}
        </p>
      )}

      {campaigns !== null &&
        (campaigns.length === 0 ? (
          <p className="text-sm text-fg-muted">{t("campaigns.empty")}</p>
        ) : (
          <ul className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {campaigns.map((campaign) => (
              <li
                key={campaign.id}
                className="flex flex-col gap-3 rounded-2xl border border-border bg-bg-elevated p-5 shadow-[var(--shadow)]"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span className="rounded-full border border-border px-2.5 py-0.5 text-xs font-medium text-fg-muted">
                    {t(`campaigns.status_${campaign.status}`)}
                  </span>
                </div>
                <h3 className="text-lg font-medium">{campaign.name}</h3>
                <p className="text-xs text-fg-muted">
                  {t("campaigns.module_count", { count: campaign.module_count })}
                  {" · "}
                  {t("campaigns.target_count", { count: campaign.target_count })}
                </p>
                <p className="text-xs text-fg-muted">
                  {campaign.start_date || campaign.due_date
                    ? t("campaigns.dates_range", {
                        start: campaign.start_date ?? "…",
                        due: campaign.due_date ?? "…",
                      })
                    : t("campaigns.no_dates")}
                </p>
                <Link
                  to={`/content/campaigns/${campaign.id}`}
                  className="self-start rounded-full border border-border px-4 py-1.5 text-sm font-medium transition hover:-translate-y-0.5"
                >
                  {t("campaigns.edit")}
                </Link>
              </li>
            ))}
          </ul>
        ))}
    </section>
  );
}
