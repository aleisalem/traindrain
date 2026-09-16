import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import type { Assignment, AssignmentTargetType, ContentGroup, Requirement } from "./types";
import type { AssignmentsState } from "./useAssignments";

type IndividualOption = {
  id: string;
  label: string;
};

type Props = {
  moduleId: string;
  assignments: AssignmentsState;
  /** Only an Administrator may name an individual — the same boundary the
   *  server enforces with a 403. This only decides what the form offers. */
  isAdministrator: boolean;
};

const inputClassName =
  "rounded-xl border border-border bg-bg-elevated px-3.5 py-2.5 transition-colors focus:border-primary focus:outline-none";

function targetLabel(
  t: (key: string, options?: Record<string, unknown>) => string,
  target: Assignment["target"],
): string {
  if (target.type === "group") {
    return t("assignments.assigned_to_group", { name: target.name ?? "" });
  }
  return target.name
    ? t("assignments.assigned_to_individual", { name: target.name })
    : t("assignments.assigned_to_individual_hidden");
}

function AssignmentRow({
  assignment,
  disabled,
  onRemove,
}: {
  assignment: Assignment;
  disabled: boolean;
  onRemove: () => void;
}) {
  const { t } = useTranslation();

  return (
    <li className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border bg-bg-elevated p-3 text-sm">
      <div className="flex flex-col gap-0.5">
        <span className="font-medium">{targetLabel(t, assignment.target)}</span>
        <span className="text-xs text-fg-muted">
          {t(`assignments.requirement_${assignment.requirement}`)}
          {" · "}
          {assignment.due_date
            ? t("assignments.due_on", { date: assignment.due_date })
            : t("assignments.no_due_date")}
        </span>
      </div>
      <button
        type="button"
        disabled={disabled}
        onClick={onRemove}
        className="rounded-full border border-danger px-3 py-1 text-xs font-medium text-danger disabled:opacity-40"
      >
        {t("assignments.remove_button")}
      </button>
    </li>
  );
}

/**
 * Who a module's material is assigned to: groups for any Content Manager,
 * an individual only for an Administrator.
 *
 * The group dropdown carries only names and member counts (`ContentGroup`,
 * from `GET /api/content/groups`) — the same view a Content Manager gets
 * everywhere else, never a member list. The individual dropdown, fetched only
 * when `isAdministrator`, is the one place this screen reaches into
 * `/api/admin/users`, which an Administrator already has full access to.
 */
export function AssignmentsPanel({ moduleId, assignments, isAdministrator }: Props) {
  const { t } = useTranslation();
  const [groups, setGroups] = useState<ContentGroup[]>([]);
  const [individuals, setIndividuals] = useState<IndividualOption[]>([]);
  const [targetType, setTargetType] = useState<AssignmentTargetType>("group");
  const [targetId, setTargetId] = useState("");
  const [dueDate, setDueDate] = useState("");
  const [requirement, setRequirement] = useState<Requirement>("mandatory");
  const [autoReminders, setAutoReminders] = useState(true);
  const [reminding, setReminding] = useState(false);
  const [remindMessage, setRemindMessage] = useState<{ kind: "success" | "error"; text: string } | null>(
    null,
  );

  async function handleRemind() {
    setReminding(true);
    setRemindMessage(null);
    try {
      const response = await fetch(`/api/content/modules/${moduleId}/remind`, { method: "POST" });
      if (response.status === 429) {
        setRemindMessage({ kind: "error", text: t("assignments.remind_rate_limited") });
        return;
      }
      if (!response.ok) {
        setRemindMessage({ kind: "error", text: t("assignments.remind_error") });
        return;
      }
      const body: { sent_count: number } = await response.json();
      setRemindMessage({
        kind: "success",
        text: t("assignments.remind_success", { count: body.sent_count }),
      });
    } catch {
      setRemindMessage({ kind: "error", text: t("assignments.remind_error") });
    } finally {
      setReminding(false);
    }
  }

  useEffect(() => {
    let cancelled = false;
    async function loadGroups() {
      try {
        const response = await fetch("/api/content/groups");
        if (!response.ok || cancelled) return;
        setGroups(await response.json());
      } catch {
        // The list below still renders; only the "assign to a group" picker
        // has nothing to offer.
      }
    }
    void loadGroups();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!isAdministrator) return;
    let cancelled = false;
    type AdminUser = {
      id: string;
      email: string;
      first_name: string | null;
      last_name: string | null;
      disabled_at: string | null;
      erased_at: string | null;
    };
    async function loadIndividuals() {
      try {
        const response = await fetch("/api/admin/users");
        if (!response.ok || cancelled) return;
        const users: AdminUser[] = await response.json();
        setIndividuals(
          users
            .filter((user) => user.disabled_at === null && user.erased_at === null)
            .map((user) => ({
              id: user.id,
              label:
                [user.first_name, user.last_name].filter(Boolean).join(" ") || user.email,
            })),
        );
      } catch {
        // The individual picker simply stays empty.
      }
    }
    void loadIndividuals();
    return () => {
      cancelled = true;
    };
  }, [isAdministrator]);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!targetId) return;
    const ok = await assignments.create({
      targetType,
      targetId,
      dueDate: dueDate === "" ? null : dueDate,
      requirement,
      autoReminders,
    });
    if (ok) {
      setTargetId("");
      setDueDate("");
    }
  }

  if (assignments.loadError) {
    return (
      <section className="flex flex-col gap-3 rounded-2xl border border-border bg-bg-elevated p-5 shadow-[var(--shadow)]">
        <h3 className="text-lg font-medium">{t("assignments.heading")}</h3>
        <p role="alert" className="text-sm text-danger">
          {t("assignments.load_error")}
        </p>
      </section>
    );
  }

  const targetOptions = targetType === "group" ? groups : individuals;

  return (
    <section className="flex flex-col gap-4 rounded-2xl border border-border bg-bg-elevated p-5 shadow-[var(--shadow)]">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-lg font-medium">{t("assignments.heading")}</h3>
          <p className="text-sm text-fg-muted">{t("assignments.description")}</p>
        </div>
        {isAdministrator && (
          <button
            type="button"
            disabled={reminding}
            onClick={() => void handleRemind()}
            className="shrink-0 rounded-full border border-border px-4 py-2 text-xs font-medium transition hover:-translate-y-0.5 disabled:opacity-60 disabled:hover:translate-y-0"
          >
            {t("assignments.remind_button")}
          </button>
        )}
      </div>

      {remindMessage && (
        <p
          role={remindMessage.kind === "error" ? "alert" : "status"}
          className={remindMessage.kind === "error" ? "text-sm text-danger" : "text-sm text-fg-muted"}
        >
          {remindMessage.text}
        </p>
      )}

      {assignments.assignments.length === 0 ? (
        <p className="text-sm text-fg-muted">{t("assignments.empty")}</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {assignments.assignments.map((assignment) => (
            <AssignmentRow
              key={assignment.id}
              assignment={assignment}
              disabled={assignments.busy}
              onRemove={() => void assignments.remove(assignment.id)}
            />
          ))}
        </ul>
      )}

      {assignments.error && (
        <p role="alert" className="text-sm text-danger">
          {assignments.error}
        </p>
      )}

      <form onSubmit={(event) => void handleSubmit(event)} className="flex flex-col gap-3">
        <fieldset className="flex flex-wrap gap-4 text-sm">
          <legend className="mb-1 w-full text-sm font-medium">
            {t("assignments.target_type_legend")}
          </legend>
          <label className="flex items-center gap-1.5">
            <input
              type="radio"
              name={`target-type-${moduleId}`}
              checked={targetType === "group"}
              onChange={() => {
                setTargetType("group");
                setTargetId("");
              }}
            />
            {t("assignments.target_group_label")}
          </label>
          {isAdministrator && (
            <label className="flex items-center gap-1.5">
              <input
                type="radio"
                name={`target-type-${moduleId}`}
                checked={targetType === "user"}
                onChange={() => {
                  setTargetType("user");
                  setTargetId("");
                }}
              />
              {t("assignments.target_individual_label")}
            </label>
          )}
        </fieldset>

        <label className="flex flex-col gap-1 text-sm">
          {targetType === "group"
            ? t("assignments.target_group_label")
            : t("assignments.target_individual_label")}
          <select
            value={targetId}
            onChange={(event) => setTargetId(event.target.value)}
            className={inputClassName}
          >
            <option value="">
              {targetType === "group"
                ? t("assignments.target_group_placeholder")
                : t("assignments.target_individual_placeholder")}
            </option>
            {targetType === "group"
              ? groups.map((group) => (
                  <option key={group.id} value={group.id}>
                    {group.name} ({t("assignments.member_count", { count: group.member_count })})
                  </option>
                ))
              : individuals.map((individual) => (
                  <option key={individual.id} value={individual.id}>
                    {individual.label}
                  </option>
                ))}
          </select>
        </label>

        <label className="flex flex-col gap-1 text-sm">
          {t("assignments.due_date_label")}
          <input
            type="date"
            value={dueDate}
            onChange={(event) => setDueDate(event.target.value)}
            className={inputClassName}
          />
        </label>

        <label className="flex flex-col gap-1 text-sm">
          {t("assignments.requirement_label")}
          <select
            value={requirement}
            onChange={(event) => setRequirement(event.target.value as Requirement)}
            className={inputClassName}
          >
            <option value="mandatory">{t("assignments.requirement_mandatory")}</option>
            <option value="recommended">{t("assignments.requirement_recommended")}</option>
          </select>
        </label>

        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={autoReminders}
            onChange={(event) => setAutoReminders(event.target.checked)}
          />
          {t("assignments.auto_reminders_label")}
        </label>

        <button
          type="submit"
          disabled={assignments.busy || !targetId || targetOptions.length === 0}
          className="self-start rounded-full bg-[image:var(--gradient)] px-5 py-2 text-sm font-semibold text-primary-fg transition hover:-translate-y-0.5 hover:shadow-[var(--shadow)] disabled:opacity-60 disabled:hover:translate-y-0"
        >
          {t("assignments.assign_button")}
        </button>
      </form>
    </section>
  );
}
