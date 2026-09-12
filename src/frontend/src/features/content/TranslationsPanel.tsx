import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import type { ModuleBody } from "./types";
import type { TranslationGroupState } from "./useTranslationGroup";

const pillButtonClassName =
  "rounded-full border border-border bg-bg-elevated px-3 py-1 text-xs font-medium transition hover:-translate-y-0.5 hover:shadow-[var(--shadow)] disabled:opacity-50 disabled:hover:translate-y-0";

/**
 * A module's translation siblings: who they are, which is primary, and a way
 * to link another already-authored module in as a new one.
 *
 * Linking (rather than only ever creating a variant from scratch) is what lets
 * two modules an author wrote independently, before realizing they were the
 * same material, become one translation group after the fact.
 */
export function TranslationsPanel({ translations }: { translations: TranslationGroupState }) {
  const { t } = useTranslation();
  const [candidates, setCandidates] = useState<ModuleBody[] | null>(null);
  const [selected, setSelected] = useState("");

  const groupId = translations.group?.id;

  useEffect(() => {
    if (!groupId) return;
    let cancelled = false;
    async function load() {
      try {
        const response = await fetch("/api/content/modules");
        if (!response.ok || cancelled) return;
        setCandidates(await response.json());
      } catch {
        // Nothing to link from is a smaller failure than a crashed panel —
        // the sibling list above still renders.
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [groupId]);

  if (translations.loading) return null;
  if (translations.loadError || translations.group === null) {
    return (
      <section className="flex flex-col gap-2 rounded-2xl border border-border bg-bg-elevated p-5 shadow-[var(--shadow)]">
        <h3 className="text-lg font-medium">{t("content.translations_heading")}</h3>
        <p role="alert" className="text-sm text-danger">
          {t("content.load_error")}
        </p>
      </section>
    );
  }

  const { group } = translations;
  const usedLanguages = new Set(group.variants.map((variant) => variant.language));
  // Only modules that are not already one of this group's variants, and would
  // not immediately collide on language if linked.
  const options = (candidates ?? []).filter(
    (candidate) =>
      candidate.translation_group_id !== group.id &&
      candidate.status !== "deleted" &&
      !usedLanguages.has(candidate.language),
  );

  async function handleLink() {
    if (!selected) return;
    const ok = await translations.link(selected);
    if (ok) setSelected("");
  }

  return (
    <section className="flex flex-col gap-4 rounded-2xl border border-border bg-bg-elevated p-5 shadow-[var(--shadow)]">
      <div>
        <h3 className="text-lg font-medium">{t("content.translations_heading")}</h3>
        <p className="text-sm text-fg-muted">{t("content.translations_description")}</p>
      </div>

      <ul className="flex flex-col gap-2">
        {group.variants.map((variant) => (
          <li
            key={variant.id}
            className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-border px-3 py-2 text-sm"
          >
            <div className="flex items-center gap-2">
              <span className="rounded-full border border-border px-2 py-0.5 text-xs font-medium uppercase">
                {variant.language}
              </span>
              <span>{variant.title}</span>
              <span className="text-xs text-fg-muted">
                {t(`content.status_${variant.status}`)}
              </span>
            </div>
            {variant.id === group.primary_module_id ? (
              <span className="rounded-full bg-primary/10 px-2.5 py-0.5 text-xs font-medium text-primary">
                {t("content.translations_primary_badge")}
              </span>
            ) : (
              <button
                type="button"
                disabled={translations.busy}
                onClick={() => void translations.setPrimary(variant.id)}
                className={pillButtonClassName}
              >
                {t("content.translations_make_primary")}
              </button>
            )}
          </li>
        ))}
      </ul>

      {options.length > 0 && (
        <div className="flex flex-wrap items-end gap-2">
          <label className="flex flex-col gap-1 text-sm">
            {t("content.translations_link_label")}
            <select
              value={selected}
              onChange={(event) => setSelected(event.target.value)}
              className="rounded-xl border border-border bg-bg-elevated px-3.5 py-2.5 transition-colors focus:border-primary focus:outline-none"
            >
              <option value="">{t("content.translations_link_placeholder")}</option>
              {options.map((candidate) => (
                <option key={candidate.id} value={candidate.id}>
                  {candidate.title} ({t(`content.language_${candidate.language}`)})
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            disabled={!selected || translations.busy}
            onClick={() => void handleLink()}
            className="rounded-full border border-border bg-bg-elevated px-4 py-2 text-sm font-medium transition hover:-translate-y-0.5 hover:shadow-[var(--shadow)] disabled:opacity-50 disabled:hover:translate-y-0"
          >
            {t("content.translations_link_button")}
          </button>
        </div>
      )}

      {translations.error && (
        <p role="alert" className="text-sm text-danger">
          {translations.error}
        </p>
      )}
    </section>
  );
}
