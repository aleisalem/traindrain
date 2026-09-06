import { useCallback, useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

type GroupBody = {
  id: string;
  name: string;
  description: string | null;
  created_at: string;
};

type UserBody = {
  id: string;
  email: string;
  groups: string[];
};

type RowAction = { kind: "idle" } | { kind: "error"; message: string };

type EditState = { name: string; description: string };

export function AdminGroupsPage() {
  const { t } = useTranslation();
  const [groups, setGroups] = useState<GroupBody[] | null>(null);
  const [users, setUsers] = useState<UserBody[] | null>(null);
  const [loadError, setLoadError] = useState(false);

  const [createName, setCreateName] = useState("");
  const [createDescription, setCreateDescription] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const [editing, setEditing] = useState<Record<string, EditState>>({});
  const [confirmingDelete, setConfirmingDelete] = useState<Record<string, boolean>>({});
  const [selection, setSelection] = useState<Record<string, string>>({});
  const [rowActions, setRowActions] = useState<Record<string, RowAction>>({});
  const [busyKey, setBusyKey] = useState<string | null>(null);

  const load = useCallback(async () => {
    const [groupsResponse, usersResponse] = await Promise.all([
      fetch("/api/admin/groups"),
      fetch("/api/admin/users"),
    ]);
    if (!groupsResponse.ok || !usersResponse.ok) {
      setLoadError(true);
      return;
    }
    setLoadError(false);
    setGroups(await groupsResponse.json());
    setUsers(await usersResponse.json());
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  function setRowAction(key: string, action: RowAction) {
    setRowActions((current) => ({ ...current, [key]: action }));
  }

  async function handleCreate(event: FormEvent) {
    event.preventDefault();
    setCreating(true);
    setCreateError(null);

    const response = await fetch("/api/admin/groups", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: createName, description: createDescription || null }),
    });
    setCreating(false);

    if (response.status === 201) {
      setCreateName("");
      setCreateDescription("");
      await load();
      return;
    }
    setCreateError(
      response.status === 409
        ? t("adminGroups.create_error_conflict")
        : t("adminGroups.create_error_unknown"),
    );
  }

  function startEdit(group: GroupBody) {
    setEditing((current) => ({
      ...current,
      [group.id]: { name: group.name, description: group.description ?? "" },
    }));
  }

  function cancelEdit(groupId: string) {
    setEditing((current) => {
      const next = { ...current };
      delete next[groupId];
      return next;
    });
  }

  async function saveEdit(groupId: string) {
    const edit = editing[groupId];
    if (!edit) return;
    const key = `edit:${groupId}`;
    setBusyKey(key);
    const response = await fetch(`/api/admin/groups/${groupId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: edit.name, description: edit.description || null }),
    });
    setBusyKey(null);

    if (response.status === 200) {
      cancelEdit(groupId);
      setRowAction(key, { kind: "idle" });
      await load();
      return;
    }
    setRowAction(key, {
      kind: "error",
      message:
        response.status === 409
          ? t("adminGroups.error_conflict_update")
          : t("adminGroups.error_unknown"),
    });
  }

  async function deleteGroup(groupId: string) {
    const key = `delete:${groupId}`;
    setBusyKey(key);
    const response = await fetch(`/api/admin/groups/${groupId}`, { method: "DELETE" });
    setBusyKey(null);

    if (response.status === 204) {
      setConfirmingDelete((current) => ({ ...current, [groupId]: false }));
      await load();
      return;
    }
    setRowAction(key, { kind: "error", message: t("adminGroups.error_unknown") });
  }

  async function addMember(groupId: string) {
    const userId = selection[groupId];
    if (!userId) return;
    const key = `add:${groupId}`;
    setBusyKey(key);
    const response = await fetch(`/api/admin/groups/${groupId}/members/${userId}`, {
      method: "POST",
    });
    setBusyKey(null);

    if (response.status === 204) {
      setRowAction(key, { kind: "idle" });
      setSelection((current) => ({ ...current, [groupId]: "" }));
      await load();
      return;
    }
    setRowAction(key, {
      kind: "error",
      message:
        response.status === 409
          ? t("adminGroups.error_conflict_add")
          : t("adminGroups.error_unknown"),
    });
  }

  async function removeMember(groupId: string, userId: string) {
    const key = `remove:${groupId}:${userId}`;
    setBusyKey(key);
    const response = await fetch(`/api/admin/groups/${groupId}/members/${userId}`, {
      method: "DELETE",
    });
    setBusyKey(null);

    if (response.status === 204) {
      setRowAction(key, { kind: "idle" });
      await load();
      return;
    }
    setRowAction(key, {
      kind: "error",
      message:
        response.status === 409
          ? t("adminGroups.error_conflict_remove")
          : t("adminGroups.error_unknown"),
    });
  }

  if (loadError) {
    return (
      <section className="flex flex-col gap-4">
        <h2 className="text-xl font-semibold">{t("adminGroups.heading")}</h2>
        <p role="alert" className="text-sm text-danger">
          {t("adminGroups.load_error")}
        </p>
      </section>
    );
  }

  if (groups === null || users === null) return null;

  return (
    <section className="flex flex-col gap-6">
      <div>
        <h2 className="text-xl font-semibold">{t("adminGroups.heading")}</h2>
        <p className="text-sm text-fg-muted">{t("adminGroups.description")}</p>
      </div>

      <div className="flex flex-col gap-3 rounded-lg border border-border p-4">
        <h3 className="text-lg font-medium">{t("adminGroups.create_heading")}</h3>
        <form onSubmit={(event) => void handleCreate(event)} className="flex flex-col gap-3">
          <label className="flex flex-col gap-1 text-sm">
            {t("adminGroups.name_label")}
            <input
              type="text"
              required
              value={createName}
              onChange={(event) => setCreateName(event.target.value)}
              className="rounded-md border border-border bg-bg px-3 py-2"
            />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            {t("adminGroups.description_label")}
            <input
              type="text"
              value={createDescription}
              onChange={(event) => setCreateDescription(event.target.value)}
              className="rounded-md border border-border bg-bg px-3 py-2"
            />
          </label>
          {createError && (
            <p role="alert" className="text-sm text-danger">
              {createError}
            </p>
          )}
          <button
            type="submit"
            disabled={creating}
            className="self-start rounded-md bg-primary px-4 py-2 text-sm text-primary-fg disabled:opacity-60"
          >
            {t("adminGroups.create_submit")}
          </button>
        </form>
      </div>

      {groups.map((group) => {
        const members = users.filter((user) => user.groups.includes(group.name));
        const eligible = users.filter((user) => !user.groups.includes(group.name));
        const edit = editing[group.id];
        const editKey = `edit:${group.id}`;
        const editAction = rowActions[editKey] ?? { kind: "idle" };
        const deleteKey = `delete:${group.id}`;
        const deleteAction = rowActions[deleteKey] ?? { kind: "idle" };
        const addKey = `add:${group.id}`;
        const addAction = rowActions[addKey] ?? { kind: "idle" };

        return (
          <div key={group.id} className="flex flex-col gap-3 rounded-lg border border-border p-4">
            {edit ? (
              <div className="flex flex-col gap-2">
                <input
                  type="text"
                  aria-label={t("adminGroups.name_label")}
                  value={edit.name}
                  onChange={(event) =>
                    setEditing((current) => ({
                      ...current,
                      [group.id]: { ...edit, name: event.target.value },
                    }))
                  }
                  className="rounded-md border border-border bg-bg px-3 py-2 text-sm"
                />
                <input
                  type="text"
                  aria-label={t("adminGroups.description_label")}
                  value={edit.description}
                  onChange={(event) =>
                    setEditing((current) => ({
                      ...current,
                      [group.id]: { ...edit, description: event.target.value },
                    }))
                  }
                  className="rounded-md border border-border bg-bg px-3 py-2 text-sm"
                />
                {editAction.kind === "error" && (
                  <p role="alert" className="text-sm text-danger">
                    {editAction.message}
                  </p>
                )}
                <div className="flex gap-2">
                  <button
                    type="button"
                    disabled={busyKey === editKey}
                    onClick={() => void saveEdit(group.id)}
                    className="rounded-md border border-border px-3 py-1.5 text-sm disabled:opacity-60"
                  >
                    {t("adminGroups.edit_save")}
                  </button>
                  <button
                    type="button"
                    onClick={() => cancelEdit(group.id)}
                    className="rounded-md border border-border px-3 py-1.5 text-sm"
                  >
                    {t("adminGroups.edit_cancel")}
                  </button>
                </div>
              </div>
            ) : (
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h3 className="text-lg font-medium">{group.name}</h3>
                  {group.description && (
                    <p className="text-sm text-fg-muted">{group.description}</p>
                  )}
                </div>
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => startEdit(group)}
                    className="rounded-md border border-border px-3 py-1 text-sm"
                  >
                    {t("adminGroups.edit_button")}
                  </button>
                  {confirmingDelete[group.id] ? (
                    <>
                      <button
                        type="button"
                        disabled={busyKey === deleteKey}
                        onClick={() => void deleteGroup(group.id)}
                        className="rounded-md border border-danger px-3 py-1 text-sm text-danger disabled:opacity-60"
                      >
                        {t("adminGroups.delete_confirm")}
                      </button>
                      <button
                        type="button"
                        onClick={() =>
                          setConfirmingDelete((current) => ({ ...current, [group.id]: false }))
                        }
                        className="rounded-md border border-border px-3 py-1 text-sm"
                      >
                        {t("adminGroups.delete_cancel")}
                      </button>
                    </>
                  ) : (
                    <button
                      type="button"
                      onClick={() =>
                        setConfirmingDelete((current) => ({ ...current, [group.id]: true }))
                      }
                      className="rounded-md border border-danger px-3 py-1 text-sm text-danger"
                    >
                      {t("adminGroups.delete_button")}
                    </button>
                  )}
                </div>
              </div>
            )}
            {deleteAction.kind === "error" && (
              <p role="alert" className="text-sm text-danger">
                {deleteAction.message}
              </p>
            )}

            {members.length === 0 ? (
              <p className="text-sm text-fg-muted">{t("adminGroups.no_members")}</p>
            ) : (
              <ul className="flex flex-col gap-2">
                {members.map((member) => {
                  const removeKey = `remove:${group.id}:${member.id}`;
                  const removeAction = rowActions[removeKey] ?? { kind: "idle" };
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
                          onClick={() => void removeMember(group.id, member.id)}
                          className="rounded-md border border-border px-3 py-1 disabled:opacity-60"
                        >
                          {t("adminGroups.remove_button")}
                        </button>
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}

            {eligible.length > 0 && (
              <div className="flex flex-col gap-1 border-t border-border pt-3">
                {addAction.kind === "error" && (
                  <p role="alert" className="text-danger">
                    {addAction.message}
                  </p>
                )}
                <div className="flex flex-wrap items-center gap-2">
                  <label className="text-sm" htmlFor={`add-select-${group.id}`}>
                    {t("adminGroups.add_label")}
                  </label>
                  <select
                    id={`add-select-${group.id}`}
                    value={selection[group.id] ?? ""}
                    onChange={(event) =>
                      setSelection((current) => ({ ...current, [group.id]: event.target.value }))
                    }
                    className="rounded-md border border-border px-2 py-1 text-sm"
                  >
                    <option value="">{t("adminGroups.add_placeholder")}</option>
                    {eligible.map((user) => (
                      <option key={user.id} value={user.id}>
                        {user.email}
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    disabled={!selection[group.id] || busyKey === addKey}
                    onClick={() => void addMember(group.id)}
                    className="rounded-md border border-border px-3 py-1.5 text-sm disabled:opacity-60"
                  >
                    {t("adminGroups.add_button")}
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
