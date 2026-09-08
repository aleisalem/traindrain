import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import type { ModuleBody } from "./types";

export function ContentModulesPage() {
  const { t } = useTranslation();
  const [modules, setModules] = useState<ModuleBody[] | null>(null);
  const [loadError, setLoadError] = useState(false);

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

  if (loadError) {
    return (
      <section className="flex flex-col gap-4">
        <h2 className="text-xl font-semibold">{t("content.modules_heading")}</h2>
        <p role="alert" className="text-sm text-danger">
          {t("content.load_error")}
        </p>
      </section>
    );
  }

  if (modules === null) return null;

  return (
    <section className="flex flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold">{t("content.modules_heading")}</h2>
          <p className="text-sm text-fg-muted">{t("content.modules_description")}</p>
        </div>
        <Link
          to="/content/new"
          className="rounded-full bg-[image:var(--gradient)] px-5 py-2.5 text-sm font-semibold text-primary-fg transition hover:-translate-y-0.5 hover:shadow-[var(--shadow)]"
        >
          {t("content.new_module")}
        </Link>
      </div>

      {modules.length === 0 ? (
        <p className="text-sm text-fg-muted">{t("content.no_modules")}</p>
      ) : (
        <ul className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {modules.map((module) => (
            <li
              key={module.id}
              className="flex flex-col gap-3 rounded-2xl border border-border bg-bg-elevated p-5 shadow-[var(--shadow)]"
            >
              <div className="flex flex-wrap items-center gap-2">
                <span className="rounded-full border border-border px-2.5 py-0.5 text-xs font-medium uppercase">
                  {module.language}
                </span>
                <span className="rounded-full border border-border px-2.5 py-0.5 text-xs font-medium text-fg-muted">
                  {t(`content.status_${module.status}`)}
                </span>
                {module.estimated_duration_minutes !== null && (
                  <span className="text-xs text-fg-muted">
                    {t("content.duration_minutes", {
                      minutes: module.estimated_duration_minutes,
                    })}
                  </span>
                )}
              </div>
              <div className="flex flex-col gap-1">
                <h3 className="text-lg font-medium">{module.title}</h3>
                {module.description && (
                  <p className="text-sm text-fg-muted">{module.description}</p>
                )}
              </div>
              <dl className="flex flex-col gap-0.5 text-xs text-fg-muted">
                <div className="flex gap-1">
                  <dt>{t("content.created_by")}</dt>
                  <dd>{module.created_by.display_name}</dd>
                </div>
                <div className="flex gap-1">
                  <dt>{t("content.last_edited_by")}</dt>
                  <dd>{module.last_edited_by.display_name}</dd>
                </div>
              </dl>
              <Link
                to={`/content/${module.id}`}
                className="self-start rounded-full border border-border bg-bg-elevated px-4 py-1.5 text-sm font-medium transition hover:-translate-y-0.5 hover:shadow-[var(--shadow)]"
              >
                {t("content.edit_module")}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
