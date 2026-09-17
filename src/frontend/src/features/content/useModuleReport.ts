import { useCallback, useEffect, useState } from "react";

import type { ModuleReport } from "./types";

export type ModuleReportState = {
  report: ModuleReport | null;
  loading: boolean;
  loadError: boolean;
  reload: () => Promise<void>;
};

/**
 * Did this module's material land? One fetch, two possible shapes — the
 * server decides which of `ContentManagerModuleReport` (`groups`) or
 * `AdministratorModuleReport` (`learners`) comes back, based on the caller's
 * role, never a client-side choice (`app.routes.reports.get_module_report`).
 */
export function useModuleReport(moduleId: string | undefined): ModuleReportState {
  const [report, setReport] = useState<ModuleReport | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    if (!moduleId) return;
    setLoading(true);
    try {
      const response = await fetch(`/api/content/modules/${moduleId}/report`);
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
  }, [moduleId]);

  useEffect(() => {
    void load();
  }, [load]);

  return { report, loading, loadError, reload: load };
}
