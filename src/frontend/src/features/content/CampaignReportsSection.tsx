import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { CampaignReportPanel } from "./CampaignReportPanel";
import { useCampaignReport } from "./useCampaignReport";

type CampaignSummary = { id: string; name: string; status: string };

/** A campaign's report, fetched and rendered — used from the builder. */
export function CampaignReportSection({
  campaignId,
  isAdministrator,
}: {
  campaignId: string;
  isAdministrator: boolean;
}) {
  const report = useCampaignReport(campaignId);
  return (
    <CampaignReportPanel campaignId={campaignId} report={report} isAdministrator={isAdministrator} />
  );
}

const searchInputClassName =
  "rounded-xl border border-border bg-bg-elevated px-3.5 py-2.5 transition-colors focus:border-primary focus:outline-none";

/**
 * The Reports area's campaign half: the campaigns this caller may edit (the
 * server filters the list), searchable by name, each opening its report.
 */
export function CampaignReportsSection({ isAdministrator }: { isAdministrator: boolean }) {
  const { t } = useTranslation();
  const [campaigns, setCampaigns] = useState<CampaignSummary[] | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<string | undefined>(undefined);
  const report = useCampaignReport(selectedId);

  useEffect(() => {
    void (async () => {
      try {
        const response = await fetch("/api/content/campaigns");
        if (!response.ok) {
          setLoadError(true);
          return;
        }
        setCampaigns(await response.json());
      } catch {
        setLoadError(true);
      }
    })();
  }, []);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return (campaigns ?? []).filter((c) => !needle || c.name.toLowerCase().includes(needle));
  }, [campaigns, query]);

  if (loadError) {
    return (
      <p role="alert" className="text-sm text-danger">
        {t("content.load_error")}
      </p>
    );
  }
  if (campaigns === null) return null;

  const selected = campaigns.find((c) => c.id === selectedId);
  return (
    <div className="flex flex-col gap-6">
      <label className="flex flex-col gap-1 text-sm">
        {t("campaignReport.search_campaigns")}
        <input
          type="search"
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            setSelectedId(undefined);
          }}
          className={searchInputClassName}
        />
      </label>
      {filtered.length === 0 ? (
        <p className="text-sm text-fg-muted">{t("campaignReport.no_campaigns")}</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {filtered.map((campaign) => {
            const isSelected = campaign.id === selectedId;
            return (
              <li key={campaign.id}>
                <button
                  type="button"
                  aria-pressed={isSelected}
                  onClick={() => setSelectedId(isSelected ? undefined : campaign.id)}
                  className={`flex w-full flex-col gap-0.5 rounded-xl border px-4 py-3 text-left text-sm transition hover:-translate-y-0.5 hover:shadow-[var(--shadow)] ${
                    isSelected ? "border-primary" : "border-border"
                  } bg-bg-elevated`}
                >
                  <span className="font-medium">{campaign.name}</span>
                  <span className="text-xs text-fg-muted">
                    {t(`campaigns.status_${campaign.status}`)}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
      {selected && (
        <div className="flex flex-col gap-3">
          <h3 className="text-lg font-semibold">{selected.name}</h3>
          <CampaignReportPanel
            campaignId={selected.id}
            report={report}
            isAdministrator={isAdministrator}
          />
        </div>
      )}
    </div>
  );
}
