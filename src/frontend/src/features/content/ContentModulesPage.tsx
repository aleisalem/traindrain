import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import type { ModuleBody } from "./types";

const inputClassName =
  "rounded-xl border border-border bg-bg-elevated px-3.5 py-2.5 text-sm transition-colors focus:border-primary focus:outline-none";

type Filters = {
  q: string;
  language: string;
  status: string;
  tag: string;
};

const EMPTY_FILTERS: Filters = { q: "", language: "", status: "", tag: "" };

function buildQuery(filters: Filters): string {
  const params = new URLSearchParams();
  if (filters.q.trim()) params.set("q", filters.q.trim());
  if (filters.language) params.set("language", filters.language);
  if (filters.status) params.set("status", filters.status);
  if (filters.tag) params.set("tags", filters.tag);
  const query = params.toString();
  return query ? `?${query}` : "";
}

export function ContentModulesPage() {
  const { t } = useTranslation();
  const [modules, setModules] = useState<ModuleBody[] | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [searchInput, setSearchInput] = useState("");
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const [tags, setTags] = useState<string[]>([]);

  const load = useCallback(async () => {
    const response = await fetch(`/api/content/modules${buildQuery(filters)}`);
    if (!response.ok) {
      setLoadError(true);
      return;
    }
    setLoadError(false);
    setModules(await response.json());
  }, [filters]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    (async () => {
      const response = await fetch("/api/content/tags");
      if (response.ok) setTags(await response.json());
    })();
  }, []);

  // The search box updates its own value on every keystroke, but only feeds
  // the query — and so the network — once typing pauses. The other filters
  // are a single onChange each and go straight to `filters`.
  useEffect(() => {
    const handle = setTimeout(() => {
      setFilters((current) => ({ ...current, q: searchInput }));
    }, 300);
    return () => clearTimeout(handle);
  }, [searchInput]);

  function updateFilter(field: Exclude<keyof Filters, "q">, value: string) {
    setFilters((current) => ({ ...current, [field]: value }));
  }

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
        <div className="flex flex-wrap gap-2">
          <Link
            to="/content/import"
            className="rounded-full border border-border bg-bg-elevated px-4 py-2 text-sm font-medium transition hover:-translate-y-0.5 hover:shadow-[var(--shadow)]"
          >
            {t("content.import_document")}
          </Link>
          <Link
            to="/content/new"
            className="rounded-full bg-[image:var(--gradient)] px-5 py-2.5 text-sm font-semibold text-primary-fg transition hover:-translate-y-0.5 hover:shadow-[var(--shadow)]"
          >
            {t("content.new_module")}
          </Link>
        </div>
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-sm">
          {t("content.filter_search_label")}
          <input
            type="search"
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
            placeholder={t("content.filter_search_placeholder")}
            className={inputClassName}
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          {t("content.filter_language_label")}
          <select
            value={filters.language}
            onChange={(event) => updateFilter("language", event.target.value)}
            className={inputClassName}
          >
            <option value="">{t("content.filter_all_languages")}</option>
            <option value="en">{t("content.language_en")}</option>
            <option value="de">{t("content.language_de")}</option>
          </select>
        </label>
        <label className="flex flex-col gap-1 text-sm">
          {t("content.filter_status_label")}
          <select
            value={filters.status}
            onChange={(event) => updateFilter("status", event.target.value)}
            className={inputClassName}
          >
            <option value="">{t("content.filter_all_statuses")}</option>
            <option value="draft">{t("content.status_draft")}</option>
            <option value="published">{t("content.status_published")}</option>
          </select>
        </label>
        {tags.length > 0 && (
          <label className="flex flex-col gap-1 text-sm">
            {t("content.filter_tag_label")}
            <select
              value={filters.tag}
              onChange={(event) => updateFilter("tag", event.target.value)}
              className={inputClassName}
            >
              <option value="">{t("content.filter_all_tags")}</option>
              {tags.map((tag) => (
                <option key={tag} value={tag}>
                  {tag}
                </option>
              ))}
            </select>
          </label>
        )}
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
              {module.tags.length > 0 && (
                <ul className="flex flex-wrap gap-1.5">
                  {module.tags.map((tag) => (
                    <li
                      key={tag}
                      className="rounded-full bg-bg px-2 py-0.5 text-xs text-fg-muted"
                    >
                      {tag}
                    </li>
                  ))}
                </ul>
              )}
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
