import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";

import { ModalDialog } from "./ModalDialog";
import type { CampaignEditImpact } from "./types";

type Props = {
  impact: CampaignEditImpact;
  onConfirm: () => void;
  onCancel: () => void;
};

/**
 * The warning a removal from a running campaign cannot be saved past unread.
 *
 * States the number first, and focuses its own heading rather than the
 * confirming button, for the same reason `DeleteModuleDialog` does: nothing
 * here should be one keystroke from confirmed before the count has been read.
 */
export function CampaignImpactDialog({ impact, onConfirm, onCancel }: Props) {
  const { t } = useTranslation();
  const headingRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    headingRef.current?.focus();
  }, []);

  return (
    <ModalDialog labelledBy="campaign-impact-dialog-heading" onCancel={onCancel}>
      <h3
        id="campaign-impact-dialog-heading"
        ref={headingRef}
        tabIndex={-1}
        className="text-lg font-semibold focus:outline-none"
      >
        {t("campaigns.impact_heading")}
      </h3>
      <p
        role="status"
        className="rounded-xl border border-warning/40 bg-warning/10 px-4 py-3 text-sm text-warning"
      >
        {t("campaigns.impact_warning", { learners: impact.learners, records: impact.records })}
      </p>
      {impact.modules.length > 0 && (
        <ul className="list-disc pl-5 text-sm text-fg-muted">
          {impact.modules.map((row) => (
            <li key={row.translation_group_id}>
              {t("campaigns.impact_module_line", {
                title: row.title ?? t("campaigns.untitled_module"),
                count: row.records,
              })}
            </li>
          ))}
        </ul>
      )}
      <p className="text-sm text-fg-muted">{t("campaigns.impact_body")}</p>
      <div className="flex flex-wrap justify-end gap-2">
        <button
          type="button"
          onClick={onCancel}
          className="rounded-full border border-border bg-bg-elevated px-4 py-2 text-sm font-medium transition hover:-translate-y-0.5 hover:shadow-[var(--shadow)]"
        >
          {t("campaigns.impact_cancel")}
        </button>
        <button
          type="button"
          onClick={onConfirm}
          className="rounded-full border border-danger bg-danger/10 px-5 py-2 text-sm font-semibold text-danger transition hover:-translate-y-0.5 hover:bg-danger/20"
        >
          {t("campaigns.impact_confirm")}
        </button>
      </div>
    </ModalDialog>
  );
}
