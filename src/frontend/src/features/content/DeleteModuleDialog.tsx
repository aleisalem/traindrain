import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { ModalDialog } from "./ModalDialog";
import type { DeletionImpact } from "./types";

type Props = {
  moduleId: string;
  onConfirm: () => void;
  onCancel: () => void;
};

/**
 * The one warning a delete cannot be clicked past unread.
 *
 * Focuses its own heading, not the confirming button, for the same reason
 * `PublishDialog` does: nothing here should be one keystroke away from
 * confirmed before the number of completion records at stake has been read.
 */
export function DeleteModuleDialog({ moduleId, onConfirm, onCancel }: Props) {
  const { t } = useTranslation();
  const [impact, setImpact] = useState<DeletionImpact | null>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    headingRef.current?.focus();
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const response = await fetch(`/api/content/modules/${moduleId}/deletion-impact`);
        if (response.ok && !cancelled) setImpact(await response.json());
      } catch {
        // The count is context. Failing to fetch it leaves the warning below
        // unnumbered, and must never stop an author who wants to delete.
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [moduleId]);

  return (
    <ModalDialog labelledBy="delete-module-dialog-heading" onCancel={onCancel}>
      <h3
        id="delete-module-dialog-heading"
        ref={headingRef}
        tabIndex={-1}
        className="text-lg font-semibold focus:outline-none"
      >
        {t("publish.dialog_delete_heading")}
      </h3>
      <p className="text-sm text-fg-muted">{t("publish.dialog_delete_body")}</p>

      {impact !== null && (
        <p
          role="status"
          className="rounded-xl border border-warning/40 bg-warning/10 px-4 py-3 text-sm text-warning"
        >
          {impact.completion_count === 0
            ? t("publish.dialog_delete_impact_none")
            : t("publish.dialog_delete_impact_warning", { count: impact.completion_count })}
        </p>
      )}

      <div className="flex flex-wrap justify-end gap-2">
        <button
          type="button"
          onClick={onCancel}
          className="rounded-full border border-border bg-bg-elevated px-4 py-2 text-sm font-medium transition hover:-translate-y-0.5 hover:shadow-[var(--shadow)]"
        >
          {t("publish.dialog_cancel")}
        </button>
        <button
          type="button"
          onClick={onConfirm}
          className="rounded-full border border-danger bg-danger/10 px-5 py-2 text-sm font-semibold text-danger transition hover:-translate-y-0.5 hover:bg-danger/20"
        >
          {t("publish.dialog_delete_confirm")}
        </button>
      </div>
    </ModalDialog>
  );
}
