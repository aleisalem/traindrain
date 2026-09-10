import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import type { LearnerModuleSummary } from "./types";
import { useLearnerList } from "./useLearnerList";

/**
 * What this learner has started and what they have finished.
 *
 * A module withdrawn since they read it stays on the list: the completion is
 * theirs and does not evaporate because an author retired the material. It
 * simply stops offering a way back in.
 */
export function MyLearningPage() {
  const { t } = useTranslation();
  const state = useLearnerList<LearnerModuleSummary>("/api/me/modules");

  if (state.status === "error") {
    return (
      <section className="flex flex-col gap-4">
        <h2 className="text-xl font-semibold">{t("learning.mine_heading")}</h2>
        <p role="alert" className="text-sm text-danger">
          {t("learning.load_error")}
        </p>
      </section>
    );
  }

  if (state.status === "loading") return null;
  const rows = state.items;

  return (
    <section className="flex flex-col gap-6">
      <div>
        <h2 className="text-xl font-semibold">{t("learning.mine_heading")}</h2>
        <p className="text-sm text-fg-muted">{t("learning.mine_description")}</p>
      </div>

      {rows.length === 0 ? (
        <div className="flex flex-col items-start gap-3">
          <p className="text-sm text-fg-muted">{t("learning.mine_empty")}</p>
          <Link
            to="/modules/browse"
            className="rounded-full bg-[image:var(--gradient)] px-4 py-1.5 text-sm font-semibold text-primary-fg transition hover:-translate-y-0.5 hover:shadow-[var(--shadow)]"
          >
            {t("learning.mine_empty_cta")}
          </Link>
        </div>
      ) : (
        <ul className="flex flex-col gap-3">
          {rows.map((row) => (
            <li
              key={row.translation_group_id}
              className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-border bg-bg-elevated p-5 shadow-[var(--shadow)]"
            >
              <div className="flex flex-col gap-1">
                <h3 className="text-lg font-medium">{row.title}</h3>
                <p className="text-sm text-fg-muted">
                  {row.completed_at !== null
                    ? t("learning.completed_on", {
                        date: new Date(row.completed_at).toLocaleDateString(),
                        version: row.completed_version_number,
                      })
                    : t("learning.in_progress")}
                </p>
                {row.superseded_at !== null && (
                  <p className="text-sm text-warning">{t("learning.superseded")}</p>
                )}
              </div>
              {row.available ? (
                <Link
                  to={`/modules/${row.translation_group_id}`}
                  className="rounded-full border border-border bg-bg-elevated px-4 py-1.5 text-sm font-medium transition hover:-translate-y-0.5 hover:shadow-[var(--shadow)]"
                >
                  {row.completed_at !== null ? t("learning.open_again") : t("learning.continue")}
                </Link>
              ) : (
                <span className="text-sm text-fg-muted">{t("learning.unavailable_short")}</span>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
