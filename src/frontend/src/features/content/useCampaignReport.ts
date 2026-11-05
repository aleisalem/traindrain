import { useCallback, useEffect, useState } from "react";

import type { CampaignReport } from "./types";

export type CampaignReportState = {
  report: CampaignReport | null;
  loading: boolean;
  loadError: boolean;
  reload: () => Promise<void>;
};

/**
 * Did people do this programme? One fetch, two possible shapes — the server
 * decides between `groups` (Content Manager) and `learners` (Administrator)
 * from the caller's role (`app.routes.reports.get_campaign_report`).
 */
export function useCampaignReport(campaignId: string | undefined): CampaignReportState {
  const [report, setReport] = useState<CampaignReport | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    if (!campaignId) return;
    setLoading(true);
    try {
      const response = await fetch(`/api/content/campaigns/${campaignId}/report`);
      if (!response.ok) {
        setLoadError(true);
        return;
      }
      setLoadError(false);
      setReport(await response.json());
    } catch {
      setLoadError(true);
    } finally {
      setLoading(false);
    }
  }, [campaignId]);

  useEffect(() => {
    void load();
  }, [load]);

  return { report, loading, loadError, reload: load };
}
