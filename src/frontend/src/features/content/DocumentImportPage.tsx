import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { useDocumentImport } from "./useDocumentImport";

const inputClassName =
  "rounded-xl border border-border bg-bg-elevated px-3.5 py-2.5 transition-colors focus:border-primary focus:outline-none";

const ACCEPT =
  ".md,.markdown,.txt,.docx,.pdf,text/markdown,text/plain," +
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/pdf";

/**
 * Upload a Word document, a PDF, or a Markdown file and get back a fresh,
 * unpublished draft module split into pages, ready to review. Conversion is
 * lossy by nature (ticket 13), so the PDF caveat is shown up front — before
 * any upload starts, not just once one has failed — and a successful import
 * always surfaces its conversion report rather than jumping straight to the
 * new module.
 */
export function DocumentImportPage() {
  const { t } = useTranslation();
  const [file, setFile] = useState<File | null>(null);
  const [language, setLanguage] = useState("en");
  const fileInput = useRef<HTMLInputElement | null>(null);
  const { busy, error, result, submit, reset } = useDocumentImport();

  function handleSubmit() {
    if (!file) return;
    void submit(file, language);
  }

  function startOver() {
    reset();
    setFile(null);
    if (fileInput.current) fileInput.current.value = "";
  }

  if (result) {
    return (
      <section className="flex max-w-2xl flex-col gap-6">
        <div>
          <h2 className="text-xl font-semibold">{t("content.import_done_heading")}</h2>
          <p className="text-sm text-fg-muted">
            {t("content.import_done_description", { title: result.module.title })}
          </p>
        </div>

        {result.conversion_report.length > 0 && (
          <div className="flex flex-col gap-2 rounded-2xl border border-border bg-bg-elevated p-5 shadow-[var(--shadow)]">
            <h3 className="text-sm font-semibold">{t("content.import_report_heading")}</h3>
            <ul className="flex flex-col gap-1.5 text-sm text-fg-muted">
              {result.conversion_report.map((entry, index) => (
                <li key={`${entry.code}-${index}`}>{entry.message}</li>
              ))}
            </ul>
          </div>
        )}

        <div className="flex flex-wrap gap-2">
          <Link
            to={`/content/${result.module.id}`}
            className="rounded-full bg-[image:var(--gradient)] px-5 py-2.5 text-sm font-semibold text-primary-fg transition hover:-translate-y-0.5 hover:shadow-[var(--shadow)]"
          >
            {t("content.import_open_module")}
          </Link>
          <button
            type="button"
            onClick={startOver}
            className="rounded-full border border-border bg-bg-elevated px-4 py-2 text-sm font-medium transition hover:-translate-y-0.5 hover:shadow-[var(--shadow)]"
          >
            {t("content.import_another")}
          </button>
        </div>
      </section>
    );
  }

  return (
    <section className="flex max-w-2xl flex-col gap-6">
      <div>
        <h2 className="text-xl font-semibold">{t("content.import_heading")}</h2>
        <p className="text-sm text-fg-muted">{t("content.import_description")}</p>
      </div>

      <form
        onSubmit={(event) => {
          event.preventDefault();
          handleSubmit();
        }}
        className="flex flex-col gap-4 rounded-2xl border border-border bg-bg-elevated p-5 shadow-[var(--shadow)]"
      >
        <label className="flex flex-col gap-1 text-sm">
          {t("content.import_file_label")}
          <input
            ref={fileInput}
            type="file"
            accept={ACCEPT}
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            className={inputClassName}
          />
        </label>
        <p className="text-xs text-fg-muted">{t("content.import_pdf_notice")}</p>

        <label className="flex flex-col gap-1 text-sm">
          {t("content.language_label")}
          <select
            value={language}
            onChange={(event) => setLanguage(event.target.value)}
            className={inputClassName}
          >
            <option value="en">{t("content.language_en")}</option>
            <option value="de">{t("content.language_de")}</option>
          </select>
        </label>

        {error && (
          <p role="alert" className="text-sm text-danger">
            {error}
          </p>
        )}

        <div className="flex flex-wrap gap-2">
          <button
            type="submit"
            disabled={!file || busy}
            className="rounded-full bg-[image:var(--gradient)] px-5 py-2.5 text-sm font-semibold text-primary-fg transition hover:-translate-y-0.5 hover:shadow-[var(--shadow)] disabled:opacity-60 disabled:hover:translate-y-0"
          >
            {busy ? t("content.import_submitting") : t("content.import_submit")}
          </button>
          <Link
            to="/content"
            className="rounded-full border border-border bg-bg-elevated px-4 py-2 text-sm font-medium transition hover:-translate-y-0.5 hover:shadow-[var(--shadow)]"
          >
            {t("content.form_cancel")}
          </Link>
        </div>
      </form>
    </section>
  );
}
