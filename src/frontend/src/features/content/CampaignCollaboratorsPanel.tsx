import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { Campaign } from "./types";
import { useAdminUserOptions } from "./useAdminUserOptions";

const inputClassName =
  "rounded-xl border border-border bg-bg-elevated px-3.5 py-2.5 text-sm transition-colors focus:border-primary focus:outline-none";
const cardClassName =
  "flex flex-col gap-4 rounded-2xl border border-border bg-bg-elevated p-5 shadow-[var(--shadow)]";

type Props = {
  campaign: Campaign;
  isAdministrator: boolean;
  onChanged: (campaign: Campaign) => void;
};

/**
 * Who works on a campaign. Everyone who can open it sees the list; only the
 * creator or an Administrator (`campaign.can_manage`, decided by the server)
 * gets the controls. Reassigning the creator is an Administrator's rescue for
 * an orphaned campaign and is the one place here that reaches into
 * `/api/admin/users`.
 */
export function CampaignCollaboratorsPanel({ campaign, isAdministrator, onChanged }: Props) {
  const { t } = useTranslation();
  const base = `/api/content/campaigns/${campaign.id}`;
  const users = useAdminUserOptions(isAdministrator);
  const [email, setEmail] = useState("");
  const [newOwner, setNewOwner] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function send(url: string, init: RequestInit): Promise<boolean> {
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(url, init);
      if (!response.ok) {
        let key = "error_unknown";
        if (response.status === 404) key = "collaborator_error_not_found";
        else if (response.status === 403) key = "error_forbidden";
        else if (response.status === 409) {
          // The server's two conflicts differ: wrong role vs. already on the campaign.
          const { detail } = await response.json().catch(() => ({ detail: "" }));
          key = /already|owner/i.test(String(detail))
            ? "collaborator_error_conflict"
            : "collaborator_error_role";
        }
        setError(t(`campaigns.${key}`));
        return false;
      }
      onChanged(await response.json());
      return true;
    } catch {
      setError(t("campaigns.error_unknown"));
      return false;
    } finally {
      setBusy(false);
    }
  }

  // Not a <form>: this panel renders inside the builder's own form, and
  // nested forms submit the outer one.
  async function handleAdd() {
    if (!email.trim()) return;
    const ok = await send(`${base}/collaborators`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: email.trim() }),
    });
    if (ok) setEmail("");
  }

  async function handleReassign() {
    if (!newOwner) return;
    const ok = await send(`${base}/owner`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: newOwner }),
    });
    if (ok) setNewOwner("");
  }

  return (
    <section className={cardClassName} aria-labelledby="collaborators-heading">
      <div>
        <h3 id="collaborators-heading" className="text-lg font-medium">
          {t("campaigns.collaborators_heading")}
        </h3>
        <p className="text-sm text-fg-muted">
          {campaign.can_manage
            ? t("campaigns.collaborators_description")
            : t("campaigns.collaborators_readonly")}
        </p>
      </div>

      <p className="text-sm">
        {t("campaigns.creator_label", { name: campaign.created_by.display_name })}
      </p>

      {campaign.collaborators.length === 0 ? (
        <p className="text-sm text-fg-muted">{t("campaigns.collaborators_empty")}</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {campaign.collaborators.map((person) => (
            <li
              key={person.id}
              className="flex items-center justify-between gap-3 rounded-xl border border-border bg-bg p-3 text-sm"
            >
              <span className="font-medium">{person.display_name}</span>
              {campaign.can_manage && (
                <button
                  type="button"
                  disabled={busy}
                  aria-label={t("campaigns.remove_collaborator", { name: person.display_name })}
                  onClick={() =>
                    void send(`${base}/collaborators/${person.id}`, { method: "DELETE" })
                  }
                  className="rounded-full border border-danger px-3 py-1 text-xs font-medium text-danger disabled:opacity-40"
                >
                  ✕
                </button>
              )}
            </li>
          ))}
        </ul>
      )}

      {campaign.can_manage && (
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex min-w-0 flex-1 flex-col gap-1 text-sm">
            {t("campaigns.collaborator_email_label")}
            <input
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  void handleAdd();
                }
              }}
              className={inputClassName}
            />
          </label>
          <button
            type="button"
            onClick={() => void handleAdd()}
            disabled={busy || !email.trim()}
            className="rounded-full border border-border px-4 py-2.5 text-sm font-medium disabled:opacity-40"
          >
            {t("campaigns.add_collaborator_button")}
          </button>
        </div>
      )}

      {isAdministrator && (
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex min-w-0 flex-1 flex-col gap-1 text-sm">
            {t("campaigns.reassign_label")}
            <select
              value={newOwner}
              onChange={(event) => setNewOwner(event.target.value)}
              className={inputClassName}
            >
              <option value="">{t("campaigns.reassign_placeholder")}</option>
              {users
                .filter((user) => user.id !== campaign.created_by.id)
                .map((user) => (
                  <option key={user.id} value={user.id}>
                    {user.label}
                  </option>
                ))}
            </select>
          </label>
          <button
            type="button"
            disabled={busy || !newOwner}
            onClick={() => void handleReassign()}
            className="rounded-full border border-border px-4 py-2.5 text-sm font-medium disabled:opacity-40"
          >
            {t("campaigns.reassign_button")}
          </button>
        </div>
      )}

      {error && (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      )}
    </section>
  );
}
