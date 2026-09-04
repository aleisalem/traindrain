import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

type UserRow = {
  id: string;
  email: string;
  firstName: string | null;
  lastName: string | null;
  roles: string[];
  disabledAt: string | null;
  erasedAt: string | null;
};

type UserListItemBody = {
  id: string;
  email: string;
  first_name: string | null;
  last_name: string | null;
  roles: string[];
  disabled_at: string | null;
  erased_at: string | null;
};

type RowAction = { kind: "idle" } | { kind: "confirming_erase" } | { kind: "error"; message: string };

type Props = {
  currentUserId: string;
};

function toUserRow(body: UserListItemBody): UserRow {
  return {
    id: body.id,
    email: body.email,
    firstName: body.first_name,
    lastName: body.last_name,
    roles: body.roles,
    disabledAt: body.disabled_at,
    erasedAt: body.erased_at,
  };
}

export function AdminUsersPage({ currentUserId }: Props) {
  const { t } = useTranslation();
  const [users, setUsers] = useState<UserRow[] | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [rowActions, setRowActions] = useState<Record<string, RowAction>>({});
  const [busyUserId, setBusyUserId] = useState<string | null>(null);

  const loadUsers = useCallback(async () => {
    const response = await fetch("/api/admin/users");
    if (!response.ok) {
      setLoadError(true);
      return;
    }
    setLoadError(false);
    const body: UserListItemBody[] = await response.json();
    setUsers(body.map(toUserRow));
  }, []);

  useEffect(() => {
    void loadUsers();
  }, [loadUsers]);

  function setRowAction(userId: string, action: RowAction) {
    setRowActions((current) => ({ ...current, [userId]: action }));
  }

  async function runAction(userId: string, action: "disable" | "enable" | "erase") {
    setBusyUserId(userId);
    const response = await fetch(`/api/admin/users/${userId}/${action}`, { method: "POST" });
    setBusyUserId(null);

    if (response.status === 204) {
      setRowAction(userId, { kind: "idle" });
      await loadUsers();
      return;
    }
    setRowAction(userId, {
      kind: "error",
      message:
        response.status === 409
          ? t(`adminUsers.error_conflict_${action}`)
          : t("adminUsers.error_unknown"),
    });
  }

  if (loadError) {
    return (
      <section className="flex flex-col gap-4">
        <h2 className="text-xl font-semibold">{t("adminUsers.heading")}</h2>
        <p role="alert" className="text-sm text-danger">
          {t("adminUsers.load_error")}
        </p>
      </section>
    );
  }

  if (users === null) return null;

  return (
    <section className="flex flex-col gap-4">
      <h2 className="text-xl font-semibold">{t("adminUsers.heading")}</h2>
      <p className="text-sm text-fg-muted">{t("adminUsers.description")}</p>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] text-left text-sm">
          <thead>
            <tr className="border-b border-border text-fg-muted">
              <th className="py-2 pr-4 font-medium">{t("adminUsers.column_email")}</th>
              <th className="py-2 pr-4 font-medium">{t("adminUsers.column_name")}</th>
              <th className="py-2 pr-4 font-medium">{t("adminUsers.column_roles")}</th>
              <th className="py-2 pr-4 font-medium">{t("adminUsers.column_status")}</th>
              <th className="py-2 font-medium">{t("adminUsers.column_actions")}</th>
            </tr>
          </thead>
          <tbody>
            {users.map((user) => {
              const isSelf = user.id === currentUserId;
              const action = rowActions[user.id] ?? { kind: "idle" };
              const status = user.erasedAt
                ? t("adminUsers.status_erased")
                : user.disabledAt
                  ? t("adminUsers.status_disabled")
                  : t("adminUsers.status_active");

              return (
                <tr key={user.id} className="border-b border-border align-top">
                  <td className="py-2 pr-4">{user.email}</td>
                  <td className="py-2 pr-4">
                    {user.firstName || user.lastName
                      ? [user.firstName, user.lastName].filter(Boolean).join(" ")
                      : "—"}
                  </td>
                  <td className="py-2 pr-4">{user.roles.join(", ") || "—"}</td>
                  <td className="py-2 pr-4">{status}</td>
                  <td className="py-2">
                    {user.erasedAt ? null : isSelf ? (
                      <span className="text-fg-muted">{t("adminUsers.self_row_note")}</span>
                    ) : (
                      <div className="flex flex-col gap-2">
                        {action.kind === "error" && (
                          <p role="alert" className="text-danger">
                            {action.message}
                          </p>
                        )}

                        {action.kind === "confirming_erase" ? (
                          <div className="flex gap-2">
                            <button
                              type="button"
                              disabled={busyUserId === user.id}
                              onClick={() => void runAction(user.id, "erase")}
                              className="rounded-md border border-danger px-3 py-1.5 text-danger disabled:opacity-60"
                            >
                              {t("adminUsers.erase_confirm")}
                            </button>
                            <button
                              type="button"
                              onClick={() => setRowAction(user.id, { kind: "idle" })}
                              className="rounded-md border border-border px-3 py-1.5"
                            >
                              {t("adminUsers.erase_cancel")}
                            </button>
                          </div>
                        ) : (
                          <div className="flex flex-wrap gap-2">
                            {user.disabledAt ? (
                              <button
                                type="button"
                                disabled={busyUserId === user.id}
                                onClick={() => void runAction(user.id, "enable")}
                                className="rounded-md border border-border px-3 py-1.5 disabled:opacity-60"
                              >
                                {t("adminUsers.enable_button")}
                              </button>
                            ) : (
                              <button
                                type="button"
                                disabled={busyUserId === user.id}
                                onClick={() => void runAction(user.id, "disable")}
                                className="rounded-md border border-border px-3 py-1.5 disabled:opacity-60"
                              >
                                {t("adminUsers.disable_button")}
                              </button>
                            )}
                            <button
                              type="button"
                              disabled={busyUserId === user.id}
                              onClick={() => setRowAction(user.id, { kind: "confirming_erase" })}
                              className="rounded-md border border-danger px-3 py-1.5 text-danger disabled:opacity-60"
                            >
                              {t("adminUsers.erase_button")}
                            </button>
                          </div>
                        )}
                      </div>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
