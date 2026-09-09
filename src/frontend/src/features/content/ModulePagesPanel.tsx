import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { SCHEMA_VERSION, emptyDocument, type PageDocument } from "../../content/schema";
import { PageEditor } from "./PageEditor";
import { PagePreview } from "./PagePreview";
import type { ModuleAssetsState } from "./useModuleAssets";

type PageBody = {
  id: string;
  position: number;
  title: string;
  schema_version: number;
  body: PageDocument;
  updated_at: string;
};

type PagesBody = {
  draft_revision: number;
  schema_version: number;
  pages: PageBody[];
};

type Draft = { pageId: string; title: string; document: PageDocument };

type Props = {
  moduleId: string;
  /** Lifted to the authoring screen, so the editor's image picker and the
   *  asset panel are looking at the same list. */
  assets: ModuleAssetsState;
};

const pillClassName =
  "rounded-full border border-border bg-bg-elevated px-4 py-1.5 text-sm font-medium transition hover:-translate-y-0.5 hover:shadow-[var(--shadow)] disabled:opacity-60 disabled:hover:translate-y-0";

export function ModulePagesPanel({ moduleId, assets }: Props) {
  const { t } = useTranslation();
  const [state, setState] = useState<PagesBody | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [previewing, setPreviewing] = useState(false);

  const load = useCallback(async () => {
    const response = await fetch(`/api/content/modules/${moduleId}/pages`);
    if (!response.ok) {
      setLoadError(true);
      return;
    }
    setLoadError(false);
    setState(await response.json());
  }, [moduleId]);

  useEffect(() => {
    void load();
  }, [load]);

  // Derived rather than stored, so a deleted or reordered page can never
  // leave the selection pointing at something that is no longer there.
  const selected =
    state?.pages.find((page) => page.id === selectedId) ?? state?.pages[0] ?? null;
  // The edit buffer belongs to the page it was typed into: if the selection
  // has moved on, the buffer is not this page's and the stored body wins.
  const editing = selected && draft?.pageId === selected.id ? draft : null;

  /** Apply a write, folding the server's fresh state (or its refusal) back in. */
  const write = useCallback(
    async (path: string, method: string, body: Record<string, unknown>) => {
      if (state === null) return null;
      setBusy(true);
      setError(null);
      setSaved(false);

      const response = await fetch(path, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ draft_revision: state.draft_revision, ...body }),
      });
      setBusy(false);

      if (response.ok) {
        const fresh: PagesBody = await response.json();
        setState(fresh);
        return fresh;
      }
      if (response.status === 409) {
        const detail = (await response.json()).detail;
        setError(
          detail?.code === "draft_conflict"
            ? t("editor.error_conflict")
            : t("editor.error_page_limit"),
        );
        return null;
      }
      if (response.status === 422) {
        setError(t("editor.error_rejected"));
        return null;
      }
      setError(t("editor.error_unknown"));
      return null;
    },
    [state, t],
  );

  async function addPage() {
    const fresh = await write(`/api/content/modules/${moduleId}/pages`, "POST", {
      title: t("editor.new_page_title"),
      schema_version: SCHEMA_VERSION,
      body: emptyDocument(),
    });
    // A new page is appended, and is what the author wants to write in next.
    if (fresh) setSelectedId(fresh.pages[fresh.pages.length - 1]?.id ?? null);
  }

  async function savePage() {
    if (!selected) return;
    // Falls back to what is on screen when nothing has been typed yet, so the
    // button always does what it says rather than silently doing nothing.
    const fresh = await write(
      `/api/content/modules/${moduleId}/pages/${selected.id}`,
      "PATCH",
      {
        title: editing?.title ?? selected.title,
        schema_version: SCHEMA_VERSION,
        body: editing?.document ?? selected.body,
      },
    );
    if (fresh) setSaved(true);
  }

  async function deletePage(pageId: string) {
    await write(`/api/content/modules/${moduleId}/pages/${pageId}`, "DELETE", {});
  }

  async function movePage(pageId: string, offset: number) {
    if (state === null) return;
    const order = state.pages.map((page) => page.id);
    const from = order.indexOf(pageId);
    const to = from + offset;
    if (from < 0 || to < 0 || to >= order.length) return;
    order.splice(to, 0, ...order.splice(from, 1));
    await write(`/api/content/modules/${moduleId}/pages/reorder`, "POST", { page_ids: order });
  }

  if (loadError) {
    return (
      <section className="flex flex-col gap-3">
        <h3 className="text-lg font-medium">{t("editor.pages_heading")}</h3>
        <p role="alert" className="text-sm text-danger">
          {t("content.load_error")}
        </p>
      </section>
    );
  }

  if (state === null) return null;

  return (
    <section className="flex flex-col gap-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-lg font-medium">{t("editor.pages_heading")}</h3>
          <p className="text-sm text-fg-muted">{t("editor.pages_description")}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            aria-pressed={previewing}
            onClick={() => setPreviewing((current) => !current)}
            className={pillClassName}
          >
            {previewing ? t("editor.exit_preview") : t("editor.preview")}
          </button>
          <button type="button" disabled={busy} onClick={() => void addPage()} className={pillClassName}>
            {t("editor.add_page")}
          </button>
        </div>
      </div>

      {error && (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      )}

      {state.pages.length === 0 ? (
        <p className="text-sm text-fg-muted">{t("editor.no_pages")}</p>
      ) : previewing ? (
        <div className="flex flex-col gap-6">
          {state.pages.map((page, index) => (
            <article
              key={page.id}
              className="flex flex-col gap-3 rounded-2xl border border-border bg-bg-elevated p-5 shadow-[var(--shadow)]"
            >
              <p className="text-xs uppercase tracking-wide text-fg-muted">
                {t("editor.page_counter", { current: index + 1, total: state.pages.length })}
              </p>
              <h4 className="text-xl font-semibold">{page.title}</h4>
              <PagePreview document={page.body} />
            </article>
          ))}
        </div>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,16rem)_minmax(0,1fr)]">
          <nav aria-label={t("editor.pages_heading")}>
            <ol className="flex flex-col gap-2">
              {state.pages.map((page, index) => (
                <li
                  key={page.id}
                  className="flex items-center gap-2 rounded-xl border border-border bg-bg-elevated p-2"
                >
                  <button
                    type="button"
                    aria-current={page.id === selected?.id}
                    onClick={() => setSelectedId(page.id)}
                    className={[
                      "flex-1 truncate rounded-lg px-2 py-1 text-left text-sm transition",
                      page.id === selected?.id
                        ? "font-semibold text-fg"
                        : "text-fg-muted hover:text-fg",
                    ].join(" ")}
                  >
                    {index + 1}. {page.title}
                  </button>
                  <button
                    type="button"
                    disabled={busy || index === 0}
                    aria-label={t("editor.move_up", { title: page.title })}
                    onClick={() => void movePage(page.id, -1)}
                    className="rounded-full border border-border px-2 py-0.5 text-xs disabled:opacity-40"
                  >
                    ↑
                  </button>
                  <button
                    type="button"
                    disabled={busy || index === state.pages.length - 1}
                    aria-label={t("editor.move_down", { title: page.title })}
                    onClick={() => void movePage(page.id, 1)}
                    className="rounded-full border border-border px-2 py-0.5 text-xs disabled:opacity-40"
                  >
                    ↓
                  </button>
                  <button
                    type="button"
                    disabled={busy}
                    aria-label={t("editor.delete_page", { title: page.title })}
                    onClick={() => void deletePage(page.id)}
                    className="rounded-full border border-danger px-2 py-0.5 text-xs text-danger disabled:opacity-40"
                  >
                    ×
                  </button>
                </li>
              ))}
            </ol>
          </nav>

          {selected && (
            <div className="flex flex-col gap-3">
              <label className="flex flex-col gap-1 text-sm">
                {t("editor.page_title_label")}
                <input
                  type="text"
                  value={editing?.title ?? selected.title}
                  maxLength={200}
                  onChange={(event) =>
                    setDraft({
                      pageId: selected.id,
                      title: event.target.value,
                      document: editing?.document ?? selected.body,
                    })
                  }
                  className="rounded-xl border border-border bg-bg-elevated px-3.5 py-2.5 transition-colors focus:border-primary focus:outline-none"
                />
              </label>

              <PageEditor
                key={selected.id}
                document={editing?.document ?? selected.body}
                onChange={(document) =>
                  setDraft({
                    pageId: selected.id,
                    title: editing?.title ?? selected.title,
                    document,
                  })
                }
                library={{
                  images: assets.images,
                  upload: (file) => assets.upload("image", file),
                  busy: assets.busy,
                }}
              />

              <div className="flex flex-wrap items-center gap-3">
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void savePage()}
                  className="rounded-full bg-[image:var(--gradient)] px-5 py-2.5 text-sm font-semibold text-primary-fg transition hover:-translate-y-0.5 hover:shadow-[var(--shadow)] disabled:opacity-60 disabled:hover:translate-y-0"
                >
                  {t("editor.save_page")}
                </button>
                {/* Saving is not publishing — nothing here reaches a learner. */}
                <span className="text-xs text-fg-muted">{t("editor.save_is_not_publish")}</span>
                {saved && (
                  <span role="status" className="text-sm text-success">
                    {t("editor.saved")}
                  </span>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
