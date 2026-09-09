import { useCallback, useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams } from "react-router-dom";

import { ModuleAssetsPanel } from "./ModuleAssetsPanel";
import { ModuleEditorsPresence } from "./ModuleEditorsPresence";
import { ModulePagesPanel } from "./ModulePagesPanel";
import { OverwriteWarningDialog } from "./OverwriteWarningDialog";
import type { ModuleBody } from "./types";
import { useModuleAssets } from "./useModuleAssets";
import { useModuleEditors } from "./useModuleEditors";

const inputClassName =
  "rounded-xl border border-border bg-bg-elevated px-3.5 py-2.5 transition-colors focus:border-primary focus:outline-none";

type FormState = {
  title: string;
  description: string;
  language: string;
  duration: string;
};

const EMPTY_FORM: FormState = { title: "", description: "", language: "en", duration: "" };

/**
 * One screen for both `/content/new` and `/content/{id}` — the fields are the
 * same, only the verb differs. Language is chosen once, at creation: it fixes
 * the text-search configuration a module's pages are indexed under, so a
 * translation is a new variant rather than an edit.
 */
export function ModuleFormPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { moduleId } = useParams();
  const isEdit = moduleId !== undefined;

  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [module, setModule] = useState<ModuleBody | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Concurrent metadata edits are allowed rather than locked, so the guard is
  // visibility: who else is here, and one deliberate confirmation before a
  // save that could land on their work.
  const [confirmingOverwrite, setConfirmingOverwrite] = useState(false);
  const editors = useModuleEditors(moduleId);
  // One owner of the module's assets: the page editor inserts from this list,
  // and the panel below manages it. Two fetches would let the two disagree.
  const assets = useModuleAssets(moduleId);

  const load = useCallback(async () => {
    if (!moduleId) return;
    const response = await fetch(`/api/content/modules/${moduleId}`);
    if (!response.ok) {
      setLoadError(true);
      return;
    }
    const body: ModuleBody = await response.json();
    setModule(body);
    setForm({
      title: body.title,
      description: body.description ?? "",
      language: body.language,
      duration: body.estimated_duration_minutes?.toString() ?? "",
    });
  }, [moduleId]);

  useEffect(() => {
    void load();
  }, [load]);

  function update(field: keyof FormState, value: string) {
    setForm((current) => ({ ...current, [field]: value }));
    setSaved(false);
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    // Someone else has this module open, so their copy of the metadata may
    // already differ from what is about to be written over it.
    if (isEdit && editors.length > 0) {
      setConfirmingOverwrite(true);
      return;
    }
    void save();
  }

  async function save() {
    setConfirmingOverwrite(false);
    setSaving(true);
    setError(null);
    setSaved(false);

    const duration = form.duration.trim() === "" ? null : Number(form.duration);
    const body = {
      title: form.title,
      description: form.description.trim() === "" ? null : form.description,
      estimated_duration_minutes: duration,
      // Only sent on create — the server rejects it on a PATCH, because a
      // module's language is fixed once its pages are indexed under it.
      ...(isEdit ? {} : { language: form.language }),
    };

    const response = await fetch(
      isEdit ? `/api/content/modules/${moduleId}` : "/api/content/modules",
      {
        method: isEdit ? "PATCH" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      },
    );
    setSaving(false);

    if (response.ok) {
      if (isEdit) {
        setModule(await response.json());
        setSaved(true);
        return;
      }
      const created: ModuleBody = await response.json();
      void navigate(`/content/${created.id}`);
      return;
    }
    setError(
      response.status === 422 ? t("content.form_error_invalid") : t("content.form_error_unknown"),
    );
  }

  if (loadError) {
    return (
      <section className="flex flex-col gap-4">
        <h2 className="text-xl font-semibold">{t("content.edit_heading")}</h2>
        <p role="alert" className="text-sm text-danger">
          {t("content.load_error")}
        </p>
      </section>
    );
  }

  if (isEdit && module === null) return null;

  return (
    <section className="flex max-w-5xl flex-col gap-6">
      <div>
        <h2 className="text-xl font-semibold">
          {isEdit ? t("content.edit_heading") : t("content.create_heading")}
        </h2>
        <p className="text-sm text-fg-muted">
          {isEdit ? t("content.edit_description") : t("content.create_description")}
        </p>
      </div>

      {isEdit && <ModuleEditorsPresence editors={editors} />}

      <form
        onSubmit={handleSubmit}
        className="flex max-w-2xl flex-col gap-4 rounded-2xl border border-border bg-bg-elevated p-5 shadow-[var(--shadow)]"
      >
        <label className="flex flex-col gap-1 text-sm">
          {t("content.title_label")}
          <input
            type="text"
            required
            maxLength={200}
            value={form.title}
            onChange={(event) => update("title", event.target.value)}
            className={inputClassName}
          />
        </label>

        <label className="flex flex-col gap-1 text-sm">
          {t("content.description_label")}
          <textarea
            rows={4}
            value={form.description}
            onChange={(event) => update("description", event.target.value)}
            className={inputClassName}
          />
        </label>

        {isEdit ? (
          <p className="text-sm text-fg-muted">
            {t("content.language_fixed", {
              language: t(`content.language_${form.language}`),
            })}
          </p>
        ) : (
          <label className="flex flex-col gap-1 text-sm">
            {t("content.language_label")}
            <select
              value={form.language}
              onChange={(event) => update("language", event.target.value)}
              className={inputClassName}
            >
              <option value="en">{t("content.language_en")}</option>
              <option value="de">{t("content.language_de")}</option>
            </select>
          </label>
        )}

        <label className="flex flex-col gap-1 text-sm">
          {t("content.duration_label")}
          <input
            type="number"
            min={1}
            max={10000}
            value={form.duration}
            onChange={(event) => update("duration", event.target.value)}
            className={inputClassName}
          />
        </label>

        {error && (
          <p role="alert" className="text-sm text-danger">
            {error}
          </p>
        )}
        {saved && (
          <p role="status" className="text-sm text-success">
            {t("content.form_saved")}
          </p>
        )}

        <div className="flex flex-wrap gap-2">
          <button
            type="submit"
            disabled={saving}
            className="rounded-full bg-[image:var(--gradient)] px-5 py-2.5 text-sm font-semibold text-primary-fg transition hover:-translate-y-0.5 hover:shadow-[var(--shadow)] disabled:opacity-60 disabled:hover:translate-y-0"
          >
            {isEdit ? t("content.form_save") : t("content.form_create")}
          </button>
          <Link
            to="/content"
            className="rounded-full border border-border bg-bg-elevated px-4 py-2 text-sm font-medium transition hover:-translate-y-0.5 hover:shadow-[var(--shadow)]"
          >
            {t("content.form_cancel")}
          </Link>
        </div>
      </form>

      {confirmingOverwrite && (
        <OverwriteWarningDialog
          editors={editors}
          onConfirm={() => void save()}
          onCancel={() => setConfirmingOverwrite(false)}
        />
      )}

      {/* Pages and assets belong to a module that already exists — there is
          nothing to attach them to until the metadata has been saved once. */}
      {isEdit && moduleId && <ModulePagesPanel moduleId={moduleId} assets={assets} />}
      {isEdit && moduleId && <ModuleAssetsPanel assets={assets} />}

      {module && (
        <dl className="flex flex-col gap-1 text-sm text-fg-muted">
          <div className="flex gap-1">
            <dt>{t("content.created_by")}</dt>
            <dd>{module.created_by.display_name}</dd>
          </div>
          <div className="flex gap-1">
            <dt>{t("content.last_edited_by")}</dt>
            <dd>{module.last_edited_by.display_name}</dd>
          </div>
        </dl>
      )}
    </section>
  );
}
