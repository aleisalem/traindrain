import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";

import type { DocumentImportResponse } from "./types";

export type DocumentImportState = {
  busy: boolean;
  error: string | null;
  result: DocumentImportResponse | null;
  submit: (file: File, language: string) => Promise<void>;
  reset: () => void;
};

/**
 * `POST /api/content/modules/document-import`: one file in, a fresh draft
 * module plus a conversion report out. The size/entry/traversal caps and the
 * ProseMirror/asset validation all happen server-side — this hook only has to
 * turn a refusal into something the author can act on, the same shape
 * `useModuleAssets`'s `describeFailure` uses for asset uploads.
 */
export function useDocumentImport(): DocumentImportState {
  const { t } = useTranslation();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<DocumentImportResponse | null>(null);

  const describeFailure = useCallback(
    async (response: Response): Promise<string> => {
      let code: string | undefined;
      let message: string | undefined;
      try {
        const detail = (await response.json()).detail;
        code = detail?.code;
        message = detail?.message;
      } catch {
        // A non-JSON body (an nginx 413 page, say) leaves both undefined.
      }
      switch (code) {
        case "empty_file":
          return t("content.import_error_empty_file");
        case "unrecognised_format":
        case "extension_mismatch":
        case "not_utf8":
          return t("content.import_error_format");
        case "bad_document":
          return t("content.import_error_bad_document");
        case "encrypted_pdf":
          return t("content.import_error_encrypted_pdf");
        case "empty_document":
          return t("content.import_error_empty_document");
        // Size/structure caps: the server's own message already names the
        // specific limit, so it's shown as-is rather than re-derived here.
        case "too_many_pages":
        case "too_many_entries":
        case "archive_too_large":
        case "suspicious_compression_ratio":
        case "unexpected_entry":
          return message ?? t("content.import_error_too_large");
        default:
          if (response.status === 413) return message ?? t("content.import_error_too_large");
          return t("content.import_error_unknown");
      }
    },
    [t],
  );

  const submit = useCallback(
    async (file: File, language: string) => {
      setBusy(true);
      setError(null);
      setResult(null);

      const form = new FormData();
      form.append("file", file);
      form.append("language", language);

      try {
        const response = await fetch("/api/content/modules/document-import", {
          method: "POST",
          body: form,
        });
        if (!response.ok) {
          setError(await describeFailure(response));
          return;
        }
        setResult(await response.json());
      } catch {
        setError(t("content.import_error_unknown"));
      } finally {
        setBusy(false);
      }
    },
    [describeFailure, t],
  );

  const reset = useCallback(() => {
    setError(null);
    setResult(null);
  }, []);

  return { busy, error, result, submit, reset };
}
