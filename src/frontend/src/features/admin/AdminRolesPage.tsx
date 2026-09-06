import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

type Role = {
  id: string;
  name: string;
};

type UserRow = {
  id: string;
  email: string;
  roles: string[];
};

type RowAction = { kind: "idle" } | { kind: "error"; message: string };

export function AdminRolesPage() {
  const { t } = useTranslation();
  const [roles, setRoles] = useState<Role[] | null>(null);
  const [users, setUsers] = useState<UserRow[] | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [selection, setSelection] = useState<Record<string, string>>({});
  const [actions, setActions] = useState<Record<string, RowAction>>({});
  const [busyKey, setBusyKey] = useState<string | null>(null);

  const load = useCallback(async () => {
    const [rolesResponse, usersResponse] = await Promise.all([
      fetch("/api/admin/roles"),
      fetch("/api/admin/users"),
    ]);
    if (!rolesResponse.ok || !usersResponse.ok) {
      setLoadError(true);
      return;
    }
    setLoadError(false);
    setRoles(await rolesResponse.json());
    setUsers(await usersResponse.json());
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  function setAction(key: string, action: RowAction) {
    setActions((current) => ({ ...current, [key]: action }));
  }

  async function assign(roleId: string) {
    const userId = selection[roleId];
    if (!userId) return;
    const key = `assign:${roleId}`;
    setBusyKey(key);
    const response = await fetch(`/api/admin/users/${userId}/roles/${roleId}`, {
      method: "POST",
    });
    setBusyKey(null);

    if (response.status === 204) {
      setAction(key, { kind: "idle" });
      setSelection((current) => ({ ...current, [roleId]: "" }));
      await load();
      return;
    }
    setAction(key, {
      kind: "error",
      message:
        response.status === 409
          ? t("adminRoles.error_conflict_assign")
          : t("adminRoles.error_unknown"),
    });
  }

  async function remove(roleId: string, userId: string) {
    const key = `remove:${roleId}:${userId}`;
    setBusyKey(key);
    const response = await fetch(`/api/admin/users/${userId}/roles/${roleId}`, {
      method: "DELETE",
    });
    setBusyKey(null);

    if (response.status === 204) {
      setAction(key, { kind: "idle" });
      await load();
      return;
    }
    setAction(key, {
      kind: "error",
      message:
        response.status === 409
          ? t("adminRoles.error_conflict_remove")
          : t("adminRoles.error_unknown"),
    });
  }

  if (loadError) {
    return (
      <section className="flex flex-col gap-4">
        <h2 className="text-xl font-semibold">{t("adminRoles.heading")}</h2>
        <p role="alert" className="text-sm text-danger">
          {t("adminRoles.load_error")}
        </p>
      </section>
    );
  }

  if (roles === null || users === null) return null;

  return (
    <section className="flex flex-col gap-6">
      <div>
        <h2 className="text-xl font-semibold">{t("adminRoles.heading")}</h2>
        <p className="text-sm text-fg-muted">{t("adminRoles.description")}</p>
      </div>

      {roles.map((role) => {
        const members = users.filter((user) => user.roles.includes(role.name));
        const eligible = users.filter((user) => !user.roles.includes(role.name));
        const assignKey = `assign:${role.id}`;
        const assignAction = actions[assignKey] ?? { kind: "idle" };

        return (
          <div key={role.id} className="flex flex-col gap-3 rounded-lg border border-border p-4">
            <h3 className="text-lg font-medium">{role.name}</h3>

            {members.length === 0 ? (
              <p className="text-sm text-fg-muted">{t("adminRoles.no_members")}</p>
            ) : (
              <ul className="flex flex-col gap-2">
                {members.map((member) => {
                  const removeKey = `remove:${role.id}:${member.id}`;
                  const removeAction = actions[removeKey] ?? { kind: "idle" };
                  return (
                    <li
                      key={member.id}
                      className="flex items-center justify-between gap-3 text-sm"
                    >
                      <span>{member.email}</span>
                      <div className="flex flex-col items-end gap-1">
                        {removeAction.kind === "error" && (
                          <p role="alert" className="text-danger">
                            {removeAction.message}
                          </p>
                        )}
                        <button
                          type="button"
                          disabled={busyKey === removeKey}
                          onClick={() => void remove(role.id, member.id)}
                          className="rounded-md border border-border px-3 py-1 disabled:opacity-60"
                        >
                          {t("adminRoles.remove_button")}
                        </button>
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}

            {eligible.length > 0 && (
              <div className="flex flex-col gap-1 border-t border-border pt-3">
                {assignAction.kind === "error" && (
                  <p role="alert" className="text-danger">
                    {assignAction.message}
                  </p>
                )}
                <div className="flex flex-wrap items-center gap-2">
                  <label className="text-sm" htmlFor={`assign-select-${role.id}`}>
                    {t("adminRoles.assign_label")}
                  </label>
                  <select
                    id={`assign-select-${role.id}`}
                    value={selection[role.id] ?? ""}
                    onChange={(event) =>
                      setSelection((current) => ({ ...current, [role.id]: event.target.value }))
                    }
                    className="rounded-md border border-border px-2 py-1 text-sm"
                  >
                    <option value="">{t("adminRoles.assign_placeholder")}</option>
                    {eligible.map((user) => (
                      <option key={user.id} value={user.id}>
                        {user.email}
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    disabled={!selection[role.id] || busyKey === assignKey}
                    onClick={() => void assign(role.id)}
                    className="rounded-md border border-border px-3 py-1.5 text-sm disabled:opacity-60"
                  >
                    {t("adminRoles.assign_button")}
                  </button>
                </div>
              </div>
            )}
          </div>
        );
      })}
    </section>
  );
}
