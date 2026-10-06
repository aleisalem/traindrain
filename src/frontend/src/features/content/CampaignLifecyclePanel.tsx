import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { Campaign } from "./types";

type Props = {
  campaign: Campaign;
  onChanged: (campaign: Campaign) => void;
};

/**
 * Activation and closing for a saved campaign.
 *
 * The server decides whether a transition is allowed — this only offers the
 * controls that could succeed from the current status and explains a refusal.
 * It acts on the *saved* campaign, so the hint above the button says so.
 */
export function CampaignLifecyclePanel({ campaign, onChanged }: Props) {
  const { t } = useTranslation();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function transition(action: "activate" | "close") {
    if (action === "close" && !window.confirm(t("campaigns.close_confirm"))) return;
    setBusy(true);
    setMessage(null);
    try {
      const response = await fetch(`/api/content/campaigns/${campaign.id}/${action}`, {
        method: "POST",
      });
      if (response.ok) {
        onChanged(await response.json());
        return;
      }
      const body = await response.json().catch(() => null);
      const detail = body?.detail;
      if (response.status === 422 && detail?.code === "campaign_not_activatable") {
        const parts: string[] = [];
        if (detail.unpublished_modules?.length) {
          const titles = campaign.modules
            .filter((row) => detail.unpublished_modules.includes(row.translation_group_id))
            .map((row) => row.title ?? t("campaigns.untitled_module"));
          parts.push(t("campaigns.activate_error_unpublished", { titles: titles.join(", ") }));
        }
        if (detail.no_targets) parts.push(t("campaigns.activate_error_no_targets"));
        setMessage(parts.join(" "));
      } else if (response.status === 409) {
        setMessage(t("campaigns.transition_error_conflict"));
      } else {
        setMessage(t("campaigns.error_unknown"));
      }
    } catch {
      setMessage(t("campaigns.error_unknown"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section
      aria-labelledby="campaign-lifecycle-heading"
      className="flex flex-col gap-3 rounded-2xl border border-border bg-bg-elevated p-5 shadow-[var(--shadow)]"
    >
      <h3 id="campaign-lifecycle-heading" className="text-lg font-semibold">
        {t("campaigns.lifecycle_heading")}
      </h3>
      <p className="text-sm text-fg-muted">
        {t("campaigns.lifecycle_status", { status: t(`campaigns.status_${campaign.status}`) })}
      </p>

      {campaign.status === "draft" && (
        <>
          <p className="text-sm text-fg-muted">{t("campaigns.activate_description")}</p>
          <button
            type="button"
            disabled={busy}
            onClick={() => void transition("activate")}
            className="self-start rounded-full bg-[image:var(--gradient)] px-6 py-2.5 text-sm font-semibold text-primary-fg transition hover:-translate-y-0.5 hover:shadow-[var(--shadow)] disabled:opacity-60"
          >
            {t("campaigns.activate_button")}
          </button>
        </>
      )}
      {campaign.status === "active" && (
        <>
          <p className="text-sm text-fg-muted">{t("campaigns.close_description")}</p>
          <button
            type="button"
            disabled={busy}
            onClick={() => void transition("close")}
            className="self-start rounded-full border border-danger px-5 py-2 text-sm font-medium text-danger disabled:opacity-60"
          >
            {t("campaigns.close_button")}
          </button>
        </>
      )}
      {campaign.status === "closed" && (
        <p className="text-sm text-fg-muted">{t("campaigns.closed_description")}</p>
      )}

      {message && (
        <p role="alert" className="text-sm text-danger">
          {message}
        </p>
      )}
    </section>
  );
}
