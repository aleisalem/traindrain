import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import type { CatalogEntry } from "./types";
import { useLearnerList } from "./useLearnerList";

const inputClassName =
  "rounded-xl border border-border bg-bg-elevated px-3.5 py-2.5 text-sm transition-colors focus:border-primary focus:outline-none";

type Filters = {
  q: string;
  language: string;
  tags: string;
};

const EMPTY_FILTERS: Filters = { q: "", language: "", tags: "" };

function buildQuery(filters: Filters): string {
  const params = new URLSearchParams();
  if (filters.q.trim()) params.set("q", filters.q.trim());
  if (filters.language) params.set("language", filters.language);
  for (const tag of filters.tags.split(",").map((tag) => tag.trim()).filter(Boolean)) {
    params.append("tags", tag);
  }
  const query = params.toString();
  return query ? `/api/catalog/modules?${query}` : "/api/catalog/modules";
}

/**
 * The open catalog: material an author deliberately put on offer to everyone.
 *
 * A module reaches this list only once it is both published and opted in, and
 * the opt-in defaults to off — so nothing arrives here by forgetting.
 */
export function CatalogPage() {
  const { t } = useTranslation();
  const [searchInput, setSearchInput] = useState("");
  const [tagsInput, setTagsInput] = useState("");
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const isFiltered = filters.q.trim() !== "" || filters.language !== "" || filters.tags.trim() !== "";
  const state = useLearnerList<CatalogEntry>(buildQuery(filters));

  // Free-text fields update their own value on every keystroke, but only
  // reach `filters` — and so the network — once typing pauses. `language` is
  // a single onChange and goes straight to `filters`.
  useEffect(() => {
    const handle = setTimeout(() => {
      setFilters((current) => ({ ...current, q: searchInput }));
    }, 300);
    return () => clearTimeout(handle);
  }, [searchInput]);

  useEffect(() => {
    const handle = setTimeout(() => {
      setFilters((current) => ({ ...current, tags: tagsInput }));
    }, 300);
    return () => clearTimeout(handle);
  }, [tagsInput]);

  function updateFilter(field: "language", value: string) {
    setFilters((current) => ({ ...current, [field]: value }));
  }

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

      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-sm">
          {t("learning.filter_search_label")}
          <input
            type="search"
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
            placeholder={t("learning.filter_search_placeholder")}
            className={inputClassName}
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          {t("learning.filter_language_label")}
          <select
            value={filters.language}
            onChange={(event) => updateFilter("language", event.target.value)}
            className={inputClassName}
          >
            <option value="">{t("learning.filter_all_languages")}</option>
            <option value="en">{t("learning.language_en")}</option>
            <option value="de">{t("learning.language_de")}</option>
          </select>
        </label>
        <label className="flex flex-col gap-1 text-sm">
          {t("learning.filter_tags_label")}
          <input
            type="text"
            value={tagsInput}
            onChange={(event) => setTagsInput(event.target.value)}
            placeholder={t("learning.filter_tags_placeholder")}
            className={inputClassName}
          />
        </label>
      </div>

      {entries.length === 0 ? (
        <p className="text-sm text-fg-muted">
          {isFiltered ? t("learning.catalog_no_results") : t("learning.catalog_empty")}
        </p>
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
                {/* Superseded first: a module the learner has been asked to
                    read again is not one they are finished with, and showing
                    both badges would leave them to work out which one counts. */}
                {entry.superseded_at !== null ? (
                  <span className="rounded-full bg-warning/15 px-2.5 py-0.5 text-xs font-medium text-warning">
                    {t("learning.badge_updated")}
                  </span>
                ) : (
                  entry.completed_at !== null && (
                    <span className="rounded-full bg-success/15 px-2.5 py-0.5 text-xs font-medium text-success">
                      {t("learning.badge_completed")}
                    </span>
                  )
                )}
              </div>
              <div className="flex flex-col gap-1">
                <h3 className="text-lg font-medium">{entry.title}</h3>
                {entry.description && (
                  <p className="text-sm text-fg-muted">{entry.description}</p>
                )}
              </div>
              {entry.tags.length > 0 && (
                <ul className="flex flex-wrap gap-1.5">
                  {entry.tags.map((tag) => (
                    <li key={tag} className="rounded-full bg-bg px-2 py-0.5 text-xs text-fg-muted">
                      {tag}
                    </li>
                  ))}
                </ul>
              )}
              <Link
                to={`/modules/${entry.translation_group_id}`}
                className="self-start rounded-full bg-[image:var(--gradient)] px-4 py-1.5 text-sm font-semibold text-primary-fg transition hover:-translate-y-0.5 hover:shadow-[var(--shadow)]"
              >
                {entry.superseded_at !== null
                  ? t("learning.read_again")
                  : entry.completed_at !== null
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
