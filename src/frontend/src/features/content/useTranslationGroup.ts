import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import type { TranslationGroupBody } from "./types";

export type TranslationGroupState = {
  group: TranslationGroupBody | null;
  loading: boolean;
  loadError: boolean;
  busy: boolean;
  error: string | null;
  link: (moduleId: string) => Promise<boolean>;
  setPrimary: (moduleId: string) => Promise<boolean>;
  clearError: () => void;
};

/**
 * A module's translation group: its sibling variants, and which is primary.
 *
 * One owner of this state for the same reason `useModuleAssets` is: the
 * sibling list and the "make primary" control both have to agree the moment
 * either one changes something.
 */
export function useTranslationGroup(groupId: string | undefined): TranslationGroupState {
  const { t } = useTranslation();
  const [group, setGroup] = useState<TranslationGroupBody | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!groupId) return;
    try {
      const response = await fetch(`/api/content/translation-groups/${groupId}`);
      if (!response.ok) {
        setLoadError(true);
        return;
      }
      setLoadError(false);
      setGroup(await response.json());
    } catch {
      setLoadError(true);
    }
  }, [groupId]);

  useEffect(() => {
    void load();
  }, [load]);

  /** Turn the server's refusal into something the author can act on. */
  const describeFailure = useCallback(
    async (response: Response): Promise<string> => {
      let code: string | undefined;
      try {
        code = (await response.json())?.detail?.code;
      } catch {
        // A non-JSON body leaves the general message below.
      }
      if (code === "language_already_exists") {
        return t("content.translations_error_language_exists");
      }
      if (code === "source_not_standalone") return t("content.translations_error_not_standalone");
      if (code === "source_has_progress") return t("content.translations_error_has_progress");
      if (code === "module_deleted" || code === "already_a_variant") {
        return t("content.translations_error_invalid");
      }
      if (response.status === 404) return t("content.translations_error_not_found");
      return t("content.translations_error_unknown");
    },
    [t],
  );

  const link = useCallback(
    async (moduleId: string): Promise<boolean> => {
      if (!groupId) return false;
      setBusy(true);
      setError(null);
      try {
        const response = await fetch(`/api/content/translation-groups/${groupId}/variants`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ module_id: moduleId }),
        });
        if (!response.ok) {
          setError(await describeFailure(response));
          return false;
        }
        setGroup(await response.json());
        return true;
      } catch {
        setError(t("content.translations_error_unknown"));
        return false;
      } finally {
        setBusy(false);
      }
    },
    [groupId, describeFailure, t],
  );

  const setPrimary = useCallback(
    async (moduleId: string): Promise<boolean> => {
      if (!groupId) return false;
      setBusy(true);
      setError(null);
      try {
        const response = await fetch(`/api/content/translation-groups/${groupId}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ primary_module_id: moduleId }),
        });
        if (!response.ok) {
          setError(await describeFailure(response));
          return false;
        }
        setGroup(await response.json());
        return true;
      } catch {
        setError(t("content.translations_error_unknown"));
        return false;
      } finally {
        setBusy(false);
      }
    },
    [groupId, describeFailure, t],
  );

  return {
    group,
    loading: group === null && !loadError,
    loadError,
    busy,
    error,
    link,
    setPrimary,
    clearError: useCallback(() => setError(null), []),
  };
}
