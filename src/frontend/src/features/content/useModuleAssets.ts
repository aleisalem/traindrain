import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { AssetKind, ModuleAsset, ModuleAssetsBody } from "./types";

export type ModuleAssetsState = {
  images: ModuleAsset[];
  attachments: ModuleAsset[];
  totalBytes: number;
  maxModuleBytes: number;
  maxImageBytes: number;
  maxAttachmentBytes: number;
  loading: boolean;
  loadError: boolean;
  busy: boolean;
  error: string | null;
  upload: (kind: AssetKind, file: File) => Promise<ModuleAsset | null>;
  remove: (assetId: string) => Promise<void>;
  clearError: () => void;
};

/**
 * One owner of a module's asset state.
 *
 * Both the asset panel and the page editor's image picker need this list, and
 * they need to agree: an image uploaded from inside the editor has to appear in
 * the panel, and one deleted in the panel must stop being offered by the
 * picker. A single hook lifted to the authoring screen is what makes that true
 * without either component polling.
 */
export function useModuleAssets(moduleId: string | undefined): ModuleAssetsState {
  const { t } = useTranslation();
  const [body, setBody] = useState<ModuleAssetsBody | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!moduleId) return;
    try {
      const response = await fetch(`/api/content/modules/${moduleId}/assets`);
      if (!response.ok) {
        setLoadError(true);
        return;
      }
      setLoadError(false);
      setBody(await response.json());
    } catch {
      setLoadError(true);
    }
  }, [moduleId]);

  useEffect(() => {
    void load();
  }, [load]);

  /** Turn the server's refusal into something the author can act on. */
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
      if (code === "svg_not_allowed") return t("assets.error_svg");
      if (code === "file_too_large" || response.status === 413) {
        return message ?? t("assets.error_too_large");
      }
      if (code === "module_quota_exceeded") return message ?? t("assets.error_quota");
      if (response.status === 415) return t("assets.error_type");
      return t("assets.error_unknown");
    },
    [t],
  );

  const upload = useCallback(
    async (kind: AssetKind, file: File): Promise<ModuleAsset | null> => {
      if (!moduleId) return null;
      setBusy(true);
      setError(null);

      const form = new FormData();
      form.append("kind", kind);
      form.append("file", file);

      try {
        const response = await fetch(`/api/content/modules/${moduleId}/assets`, {
          method: "POST",
          body: form,
        });
        if (!response.ok) {
          setError(await describeFailure(response));
          return null;
        }
        const fresh: ModuleAssetsBody = await response.json();
        setBody(fresh);
        // Newest first, so the asset just added is the one to hand back — the
        // editor inserts it straight into the page the author is writing.
        return fresh.assets[0] ?? null;
      } catch {
        setError(t("assets.error_unknown"));
        return null;
      } finally {
        setBusy(false);
      }
    },
    [moduleId, describeFailure, t],
  );

  const remove = useCallback(
    async (assetId: string) => {
      if (!moduleId) return;
      setBusy(true);
      setError(null);
      try {
        const response = await fetch(`/api/content/modules/${moduleId}/assets/${assetId}`, {
          method: "DELETE",
        });
        if (!response.ok) {
          setError(await describeFailure(response));
          return;
        }
        setBody(await response.json());
      } catch {
        setError(t("assets.error_unknown"));
      } finally {
        setBusy(false);
      }
    },
    [moduleId, describeFailure, t],
  );

  const images = useMemo(
    () => body?.assets.filter((asset) => asset.kind === "image") ?? [],
    [body],
  );
  const attachments = useMemo(
    () => body?.assets.filter((asset) => asset.kind === "attachment") ?? [],
    [body],
  );

  return {
    images,
    attachments,
    totalBytes: body?.total_bytes ?? 0,
    maxModuleBytes: body?.max_module_bytes ?? 0,
    maxImageBytes: body?.max_image_bytes ?? 0,
    maxAttachmentBytes: body?.max_attachment_bytes ?? 0,
    loading: body === null && !loadError,
    loadError,
    busy,
    error,
    upload,
    remove,
    clearError: useCallback(() => setError(null), []),
  };
}
