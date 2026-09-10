import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";

import { PublishDialog } from "./PublishDialog";
import type { ModuleBody, ModuleVersion, RevisionKind } from "./types";

/** The three things this panel can ask the server to do, which are also the
 *  URL segments they live at. */
type LifecycleAction = "publish" | "unpublish" | "duplicate";

type Props = {
  module: ModuleBody;
  /** Hands the module's new state back, so the screen above stays in step. */
  onChanged: (module: ModuleBody) => void;
};

const pillClassName =
  "rounded-full border border-border bg-bg-elevated px-4 py-2 text-sm font-medium transition hover:-translate-y-0.5 hover:shadow-[var(--shadow)] disabled:opacity-60 disabled:hover:translate-y-0";

/**
 * The line between what the author is working on and what a learner reads.
 *
 * Everything on this screen above this panel edits the draft. Nothing there
 * reaches anybody until Publish freezes a copy of it, which is why the panel
 * states the module's status in words rather than leaving it to a badge.
 */
export function ModulePublishPanel({ module, onChanged }: Props) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [versions, setVersions] = useState<ModuleVersion[]>([]);
  const [choosing, setChoosing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadVersions = useCallback(async () => {
    try {
      const response = await fetch(`/api/content/modules/${module.id}/versions`);
      if (response.ok) setVersions(await response.json());
    } catch {
      // History is context, not the point of the screen: failing to load it
      // must not stop an author publishing.
    }
  }, [module.id]);

  useEffect(() => {
    void loadVersions();
  }, [loadVersions]);

  /** Run one lifecycle action, folding the module's new state back in. */
  async function act(
    action: LifecycleAction,
    body?: Record<string, unknown>,
  ): Promise<ModuleBody | null> {
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(`/api/content/modules/${module.id}/${action}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body ?? {}),
      });
      if (!response.ok) {
        let code: string | undefined;
        try {
          code = (await response.json()).detail?.code;
        } catch {
          // A non-JSON body leaves the generic message below.
        }
        setError(code === "empty_module" ? t("publish.error_empty") : t("publish.error_unknown"));
        return null;
      }
      return await response.json();
    } catch {
      setError(t("publish.error_unknown"));
      return null;
    } finally {
      setBusy(false);
    }
  }

  async function publish(kind: RevisionKind) {
    setChoosing(false);
    const published = await act("publish", { revision_kind: kind });
    if (published) {
      onChanged(published);
      await loadVersions();
    }
  }

  async function unpublish() {
    const unpublished = await act("unpublish");
    if (unpublished) onChanged(unpublished);
  }

  async function duplicate() {
    // The copy's name is chosen here rather than server-side: "(copy)" is a
    // word, and it has to be the reader's. The title is trimmed *before* the
    // suffix goes on, so a long one loses its own tail rather than ending
    // "… (cop" — and the result still fits the column's 200 characters.
    const copy = await act("duplicate", {
      title: t("publish.copy_title", { title: module.title.slice(0, 150) }).slice(0, 200),
    });
    if (copy) void navigate(`/content/${copy.id}`);
  }

  const published = module.status === "published";

  return (
    <section className="flex flex-col gap-4 rounded-2xl border border-border bg-bg-elevated p-5 shadow-[var(--shadow)]">
      <div>
        <h3 className="text-lg font-medium">{t("publish.heading")}</h3>
        <p className="text-sm text-fg-muted">
          {published
            ? t("publish.state_published", { version: module.current_version_number })
            : module.current_version_number !== null
              ? t("publish.state_unpublished", { version: module.current_version_number })
              : t("publish.state_draft")}
        </p>
      </div>

      {error && (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      )}

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          disabled={busy}
          onClick={() => setChoosing(true)}
          className="rounded-full bg-[image:var(--gradient)] px-5 py-2 text-sm font-semibold text-primary-fg transition hover:-translate-y-0.5 hover:shadow-[var(--shadow)] disabled:opacity-60 disabled:hover:translate-y-0"
        >
          {published ? t("publish.publish_changes") : t("publish.publish")}
        </button>
        {published && (
          <button
            type="button"
            disabled={busy}
            onClick={() => void unpublish()}
            className={pillClassName}
          >
            {t("publish.unpublish")}
          </button>
        )}
        <button
          type="button"
          disabled={busy}
          onClick={() => void duplicate()}
          className={pillClassName}
        >
          {t("publish.duplicate")}
        </button>
      </div>

      {versions.length > 0 && (
        <div className="flex flex-col gap-2">
          <h4 className="text-sm font-medium">{t("publish.history_heading")}</h4>
          <ul className="flex flex-col gap-1 text-sm text-fg-muted">
            {versions.map((version) => (
              <li key={version.id} className="flex flex-wrap gap-x-2">
                <span className="font-medium text-fg">
                  {t("publish.version_number", { version: version.version_number })}
                </span>
                <span>{t(`publish.kind_${version.revision_kind}`)}</span>
                <span>{new Date(version.published_at).toLocaleDateString()}</span>
                <span>{version.published_by.display_name}</span>
                <span>{t("publish.version_pages", { count: version.page_count })}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {choosing && (
        <PublishDialog
          republish={module.current_version_number !== null}
          onConfirm={(kind) => void publish(kind)}
          onCancel={() => setChoosing(false)}
        />
      )}
    </section>
  );
}
