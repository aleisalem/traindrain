import { useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

type RoleOption = { id: string; name: string };
type GroupOption = { id: string; name: string };

type Result = { kind: "idle" } | { kind: "success"; email: string } | { kind: "error"; message: string };

function InviteExpirySettings() {
  const { t } = useTranslation();
  const [days, setDays] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState(false);

  useEffect(() => {
    async function loadExpiry() {
      const response = await fetch("/api/admin/settings/invite-expiry-days");
      if (!response.ok) return;
      const body: { days: number } = await response.json();
      setDays(body.days);
    }
    void loadExpiry();
  }, []);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (days === null) return;
    setSaving(true);
    setSaved(false);
    setError(false);

    const response = await fetch("/api/admin/settings/invite-expiry-days", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ days }),
    });
    setSaving(false);

    if (response.ok) {
      setSaved(true);
      return;
    }
    setError(true);
  }

  if (days === null) return null;

  return (
    <form
      onSubmit={(event) => void handleSubmit(event)}
      className="flex items-end gap-3 text-sm"
    >
      <label className="flex flex-col gap-1">
        {t("invites.expiry_days_label")}
        <input
          type="number"
          min={1}
          max={365}
          value={days}
          onChange={(event) => {
            setSaved(false);
            setDays(Number(event.target.value));
          }}
          className="w-24 rounded-md border border-border bg-bg px-3 py-2"
        />
      </label>
      <button
        type="submit"
        disabled={saving}
        className="rounded-md border border-border px-3 py-2 disabled:opacity-60"
      >
        {t("invites.expiry_save")}
      </button>
      {saved && <span className="text-success">{t("invites.expiry_saved")}</span>}
      {error && (
        <span role="alert" className="text-danger">
          {t("invites.expiry_error")}
        </span>
      )}
    </form>
  );
}

export function InviteUserPage() {
  const { t } = useTranslation();
  const [roles, setRoles] = useState<RoleOption[]>([]);
  const [groups, setGroups] = useState<GroupOption[]>([]);
  const [email, setEmail] = useState("");
  const [language, setLanguage] = useState<"en" | "de">("en");
  const [selectedRoleIds, setSelectedRoleIds] = useState<string[]>([]);
  const [selectedGroupIds, setSelectedGroupIds] = useState<string[]>([]);
  const [result, setResult] = useState<Result>({ kind: "idle" });
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    async function loadRoles() {
      const response = await fetch("/api/admin/roles");
      if (!response.ok) return;
      const body: RoleOption[] = await response.json();
      // Learner is always auto-assigned on acceptance — only offer the extras.
      setRoles(body.filter((role) => role.name !== "Learner"));
    }
    void loadRoles();
  }, []);

  useEffect(() => {
    async function loadGroups() {
      const response = await fetch("/api/admin/groups");
      if (!response.ok) return;
      const body: GroupOption[] = await response.json();
      setGroups(body);
    }
    void loadGroups();
  }, []);

  function toggleRole(roleId: string) {
    setSelectedRoleIds((current) =>
      current.includes(roleId) ? current.filter((id) => id !== roleId) : [...current, roleId],
    );
  }

  function toggleGroup(groupId: string) {
    setSelectedGroupIds((current) =>
      current.includes(groupId) ? current.filter((id) => id !== groupId) : [...current, groupId],
    );
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setResult({ kind: "idle" });

    const response = await fetch("/api/admin/invites", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email,
        language,
        role_ids: selectedRoleIds,
        group_ids: selectedGroupIds,
      }),
    });
    setSubmitting(false);

    if (response.status === 201) {
      setResult({ kind: "success", email });
      setEmail("");
      setSelectedRoleIds([]);
      setSelectedGroupIds([]);
      return;
    }
    if (response.status === 409) {
      setResult({ kind: "error", message: t("invites.create_error_conflict") });
      return;
    }
    setResult({ kind: "error", message: t("invites.create_error_unknown") });
  }

  return (
    <div className="flex max-w-md flex-col gap-8">
      <section className="flex flex-col gap-2">
        <h2 className="text-lg font-semibold">{t("invites.expiry_heading")}</h2>
        <InviteExpirySettings />
      </section>

      <section className="flex flex-col gap-4">
        <h2 className="text-xl font-semibold">{t("invites.create_heading")}</h2>

        <form onSubmit={(event) => void handleSubmit(event)} className="flex flex-col gap-4">
          <label className="flex flex-col gap-1 text-sm">
            {t("auth.email_label")}
            <input
              type="email"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              className="rounded-md border border-border bg-bg px-3 py-2"
            />
          </label>

          <label className="flex flex-col gap-1 text-sm">
            {t("invites.language_label")}
            <select
              value={language}
              onChange={(event) => setLanguage(event.target.value as "en" | "de")}
              className="rounded-md border border-border bg-bg px-3 py-2"
            >
              <option value="en">{t("invites.language_en")}</option>
              <option value="de">{t("invites.language_de")}</option>
            </select>
          </label>

          {roles.length > 0 && (
            <fieldset className="flex flex-col gap-2 text-sm">
              <legend>{t("invites.roles_label")}</legend>
              {roles.map((role) => (
                <label key={role.id} className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={selectedRoleIds.includes(role.id)}
                    onChange={() => toggleRole(role.id)}
                  />
                  {role.name}
                </label>
              ))}
            </fieldset>
          )}

          {groups.length > 0 && (
            <fieldset className="flex flex-col gap-2 text-sm">
              <legend>{t("invites.groups_label")}</legend>
              {groups.map((group) => (
                <label key={group.id} className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={selectedGroupIds.includes(group.id)}
                    onChange={() => toggleGroup(group.id)}
                  />
                  {group.name}
                </label>
              ))}
            </fieldset>
          )}

          {result.kind === "error" && (
            <p role="alert" className="text-sm text-danger">
              {result.message}
            </p>
          )}
          {result.kind === "success" && (
            <p className="text-sm text-success">
              {t("invites.create_success", { email: result.email })}
            </p>
          )}

          <button
            type="submit"
            disabled={submitting}
            className="self-start rounded-md bg-primary px-4 py-2 text-sm text-primary-fg disabled:opacity-60"
          >
            {t("invites.create_submit")}
          </button>
        </form>
      </section>
    </div>
  );
}
