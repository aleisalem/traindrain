import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { ModuleReportPanel } from "./ModuleReportPanel";
import type { ModuleBody } from "./types";
import { useModuleReport } from "./useModuleReport";

type Props = {
  /** Passed straight through to `ModuleReportPanel` — the frontend half of
   *  the server's own role check on the CSV export. */
  isAdministrator: boolean;
};

const searchInputClassName =
  "rounded-xl border border-border bg-bg-elevated px-3.5 py-2.5 transition-colors focus:border-primary focus:outline-none";

/**
 * Every module's report, in one place, rather than one at a time behind each
 * module's own edit screen. An author searches for the module they want to
 * check on and reads its report inline — the panel itself
 * (`ModuleReportPanel`) is unchanged, just reached from here instead of
 * `/content/{id}`.
 *
 * Search is client-side against the already-fetched module list: there is no
 * server-side search yet (that is ticket 10's job), and a title/description
 * substring match over a Content Manager's own module list is cheap enough
 * not to need one yet.
 */
export function ModuleReportsPage({ isAdministrator }: Props) {
  const { t } = useTranslation();
  const [modules, setModules] = useState<ModuleBody[] | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [query, setQuery] = useState("");
  const [selectedModuleId, setSelectedModuleId] = useState<string | undefined>(undefined);

  const load = useCallback(async () => {
    const response = await fetch("/api/content/modules");
    if (!response.ok) {
      setLoadError(true);
      return;
    }
    setLoadError(false);
    setModules(await response.json());
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const filteredModules = useMemo(() => {
    if (!modules) return [];
    const needle = query.trim().toLowerCase();
    if (!needle) return modules;
    return modules.filter(
      (module) =>
        module.title.toLowerCase().includes(needle) ||
        (module.description ?? "").toLowerCase().includes(needle),
    );
  }, [modules, query]);

  const selectedModule = modules?.find((module) => module.id === selectedModuleId) ?? null;
  const report = useModuleReport(selectedModule?.id);

  if (loadError) {
    return (
      <section className="flex flex-col gap-4">
        <h2 className="text-xl font-semibold">{t("contentReports.heading")}</h2>
        <p role="alert" className="text-sm text-danger">
          {t("content.load_error")}
        </p>
      </section>
    );
  }

  if (modules === null) return null;

  return (
    <section className="flex max-w-5xl flex-col gap-6">
      <div>
        <h2 className="text-xl font-semibold">{t("contentReports.heading")}</h2>
        <p className="text-sm text-fg-muted">{t("contentReports.description")}</p>
      </div>

      <label className="flex flex-col gap-1 text-sm">
        {t("contentReports.search_label")}
        <input
          type="search"
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            setSelectedModuleId(undefined);
          }}
          placeholder={t("contentReports.search_placeholder")}
          className={searchInputClassName}
        />
      </label>

      {filteredModules.length === 0 ? (
        <p className="text-sm text-fg-muted">{t("contentReports.no_results")}</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {filteredModules.map((module) => {
            const selected = module.id === selectedModuleId;
            return (
              <li key={module.id}>
                <button
                  type="button"
                  aria-pressed={selected}
                  onClick={() => setSelectedModuleId(selected ? undefined : module.id)}
                  className={`flex w-full flex-wrap items-center justify-between gap-2 rounded-xl border px-4 py-3 text-left text-sm transition hover:-translate-y-0.5 hover:shadow-[var(--shadow)] ${
                    selected ? "border-primary" : "border-border"
                  } bg-bg-elevated`}
                >
                  <span className="flex flex-col gap-0.5">
                    <span className="font-medium">{module.title}</span>
                    <span className="text-xs text-fg-muted">
                      {t(`content.language_${module.language}`)}
                      {" · "}
                      {t(`content.status_${module.status}`)}
                    </span>
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}

      {selectedModule && (
        <div className="flex flex-col gap-3">
          <h3 className="text-lg font-semibold">{selectedModule.title}</h3>
          <ModuleReportPanel
            moduleId={selectedModule.id}
            report={report}
            isAdministrator={isAdministrator}
          />
        </div>
      )}
    </section>
  );
}
