import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";

import { ModalDialog } from "./ModalDialog";
import type { ModuleEditor } from "./useModuleEditors";

type Props = {
  editors: ModuleEditor[];
  onConfirm: () => void;
  onCancel: () => void;
};

/**
 * The last word before a save that may land on someone else's work.
 *
 * Overwriting is allowed — this is a warning, not a lock — so the confirming
 * button says what will happen rather than "OK", and cancelling is the safe
 * default the Escape key reaches.
 */
export function OverwriteWarningDialog({ editors, onConfirm, onCancel }: Props) {
  const { t } = useTranslation();
  const confirmRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    confirmRef.current?.focus();
  }, []);

  const names = editors.map((editor) => editor.display_name).join(", ");

  return (
    <ModalDialog
      labelledBy="overwrite-warning-heading"
      describedBy="overwrite-warning-body"
      onCancel={onCancel}
    >
      <h3 id="overwrite-warning-heading" className="text-lg font-semibold">
        {t("presence.warning_heading")}
      </h3>
      <p id="overwrite-warning-body" className="text-sm text-fg-muted">
        {t("presence.warning_body", { count: editors.length, names })}
      </p>
      <div className="flex flex-wrap justify-end gap-2">
        <button
          type="button"
          onClick={onCancel}
          className="rounded-full border border-border bg-bg-elevated px-4 py-2 text-sm font-medium transition hover:-translate-y-0.5 hover:shadow-[var(--shadow)]"
        >
          {t("presence.warning_cancel")}
        </button>
        <button
          type="button"
          ref={confirmRef}
          onClick={onConfirm}
          className="rounded-full bg-[image:var(--gradient)] px-5 py-2 text-sm font-semibold text-primary-fg transition hover:-translate-y-0.5 hover:shadow-[var(--shadow)]"
        >
          {t("presence.warning_confirm")}
        </button>
      </div>
    </ModalDialog>
  );
}
