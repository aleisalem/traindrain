import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import type { CatalogEntry } from "./types";
import { useLearnerList } from "./useLearnerList";

/**
 * The open catalog: material an author deliberately put on offer to everyone.
 *
 * A module reaches this list only once it is both published and opted in, and
 * the opt-in defaults to off — so nothing arrives here by forgetting.
 */
export function CatalogPage() {
  const { t } = useTranslation();
  const state = useLearnerList<CatalogEntry>("/api/catalog/modules");

  if (state.status === "error") {
    return (
      <section className="flex flex-col gap-4">
        <h2 className="text-xl font-semibold">{t("learning.catalog_heading")}</h2>
        <p role="alert" className="text-sm text-danger">
          {t("learning.load_error")}
        </p>
      </section>
    );
  }

  if (state.status === "loading") return null;
  const entries = state.items;

  return (
    <section className="flex flex-col gap-6">
      <div>
        <h2 className="text-xl font-semibold">{t("learning.catalog_heading")}</h2>
        <p className="text-sm text-fg-muted">{t("learning.catalog_description")}</p>
      </div>

      {entries.length === 0 ? (
        <p className="text-sm text-fg-muted">{t("learning.catalog_empty")}</p>
      ) : (
        <ul className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {entries.map((entry) => (
            <li
              key={entry.translation_group_id}
              className="flex flex-col gap-3 rounded-2xl border border-border bg-bg-elevated p-5 shadow-[var(--shadow)]"
            >
              <div className="flex flex-wrap items-center gap-2">
                <span className="rounded-full border border-border px-2.5 py-0.5 text-xs font-medium uppercase">
                  {entry.language}
                </span>
                <span className="text-xs text-fg-muted">
                  {t("learning.page_count", { count: entry.page_count })}
                </span>
                {entry.estimated_duration_minutes !== null && (
                  <span className="text-xs text-fg-muted">
                    {t("learning.duration_minutes", {
                      minutes: entry.estimated_duration_minutes,
                    })}
                  </span>
                )}
                {entry.completed_at !== null && (
                  <span className="rounded-full bg-success/15 px-2.5 py-0.5 text-xs font-medium text-success">
                    {t("learning.badge_completed")}
                  </span>
                )}
              </div>
              <div className="flex flex-col gap-1">
                <h3 className="text-lg font-medium">{entry.title}</h3>
                {entry.description && (
                  <p className="text-sm text-fg-muted">{entry.description}</p>
                )}
              </div>
              <Link
                to={`/modules/${entry.translation_group_id}`}
                className="self-start rounded-full bg-[image:var(--gradient)] px-4 py-1.5 text-sm font-semibold text-primary-fg transition hover:-translate-y-0.5 hover:shadow-[var(--shadow)]"
              >
                {entry.completed_at !== null
                  ? t("learning.open_again")
                  : entry.started
                    ? t("learning.continue")
                    : t("learning.start")}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
