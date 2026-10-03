import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import type { Assignment, AssignmentTargetType, Requirement } from "./types";

export type NewAssignment = {
  targetType: AssignmentTargetType;
  targetId: string;
  dueDate: string | null;
  requirement: Requirement;
  autoReminders: boolean;
};

export type AssignmentsState = {
  assignments: Assignment[];
  loading: boolean;
  loadError: boolean;
  busy: boolean;
  error: string | null;
  create: (assignment: NewAssignment) => Promise<boolean>;
  remove: (assignmentId: string) => Promise<boolean>;
  clearError: () => void;
};

/**
 * Who a module's material is assigned to, and the two actions on that list.
 *
 * Keyed on `translationGroupId` rather than the module id in the URL: an
 * assignment always targets the group, so any of its language variants shows
 * the same list (`app.routes.assignments.list_assignments`).
 */
export function useAssignments(moduleId: string | undefined): AssignmentsState {
  const { t } = useTranslation();
  const [assignments, setAssignments] = useState<Assignment[] | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!moduleId) return;
    try {
      const response = await fetch(`/api/content/modules/${moduleId}/assignments`);
      if (!response.ok) {
        setLoadError(true);
        return;
      }
      setLoadError(false);
      setAssignments(await response.json());
    } catch {
      setLoadError(true);
    }
  }, [moduleId]);

  useEffect(() => {
    void load();
  }, [load]);

  const describeFailure = useCallback(
    async (response: Response): Promise<string> => {
      let code: string | undefined;
      try {
        code = (await response.json())?.detail?.code;
      } catch {
        // A non-JSON body leaves the general message below.
      }
      if (response.status === 403) return t("assignments.error_forbidden_individual");
      if (code === "already_assigned") return t("assignments.error_already_assigned");
      return t("assignments.error_unknown");
    },
    [t],
  );

  const create = useCallback(
    async (assignment: NewAssignment): Promise<boolean> => {
      if (!moduleId) return false;
      setBusy(true);
      setError(null);
      try {
        const response = await fetch(`/api/content/modules/${moduleId}/assignments`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            target_type: assignment.targetType,
            target_id: assignment.targetId,
            due_date: assignment.dueDate,
            requirement: assignment.requirement,
            auto_reminders: assignment.autoReminders,
          }),
        });
        if (!response.ok) {
          setError(await describeFailure(response));
          return false;
        }
        await load();
        return true;
      } catch {
        setError(t("assignments.error_unknown"));
        return false;
      } finally {
        setBusy(false);
      }
    },
    [moduleId, describeFailure, load, t],
  );

  const remove = useCallback(
    async (assignmentId: string): Promise<boolean> => {
      setBusy(true);
      setError(null);
      try {
        const response = await fetch(`/api/content/assignments/${assignmentId}`, {
          method: "DELETE",
        });
        if (!response.ok) {
          setError(await describeFailure(response));
          return false;
        }
        setAssignments((current) => current?.filter((row) => row.id !== assignmentId) ?? null);
        return true;
      } catch {
        setError(t("assignments.error_unknown"));
        return false;
      } finally {
        setBusy(false);
      }
    },
    [describeFailure, t],
  );

  return {
    assignments: assignments ?? [],
    loading: assignments === null && !loadError,
    loadError,
    busy,
    error,
    create,
    remove,
    clearError: useCallback(() => setError(null), []),
  };
}
