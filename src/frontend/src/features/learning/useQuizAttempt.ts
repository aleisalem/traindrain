import { useCallback, useState } from "react";

import type { QuizState } from "./types";

export type QuizErrorKind = "pages" | "exhausted" | "rate_limited" | "unknown";

/** The learner's calls to the quiz routes. Each returns the server's whole
 *  `QuizState`, so the component never reconstructs correctness or counts. */
export function useQuizAttempt(groupId: string) {
  const [state, setState] = useState<QuizState | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<QuizErrorKind | null>(null);
  const base = `/api/me/modules/${groupId}/quiz`;

  const call = useCallback(
    async (path: string, init?: RequestInit): Promise<QuizState | null> => {
      setError(null);
      try {
        const response = await fetch(`${base}${path}`, init);
        if (!response.ok) {
          let code = "";
          try {
            code = (await response.json())?.detail?.code ?? "";
          } catch {
            // A non-JSON body leaves the general message.
          }
          setError(
            code === "pages_outstanding"
              ? "pages"
              : code === "attempts_exhausted"
                ? "exhausted"
                : response.status === 429
                  ? "rate_limited"
                  : "unknown",
          );
          return null;
        }
        const body: QuizState = await response.json();
        setState(body);
        return body;
      } catch {
        setError("unknown");
        return null;
      }
    },
    [base],
  );

  const json = (body: unknown): RequestInit => ({
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  const load = useCallback(async () => {
    setBusy(true);
    await call("");
    setBusy(false);
  }, [call]);

  const start = useCallback(async () => {
    setBusy(true);
    const result = await call("/attempts", { method: "POST" });
    setBusy(false);
    return result;
  }, [call]);

  const answer = useCallback(
    async (attemptId: string, questionId: string, optionIds: string[]) =>
      call(`/attempts/${attemptId}/answers/${questionId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ option_ids: optionIds }),
      }),
    [call],
  );

  const submit = useCallback(
    async (attemptId: string) => {
      setBusy(true);
      const result = await call(`/attempts/${attemptId}/submit`, { method: "POST" });
      setBusy(false);
      return result;
    },
    [call],
  );

  const retake = useCallback(
    async (mode: "quiz" | "module") => {
      setBusy(true);
      const result = await call("/retake", json({ mode }));
      setBusy(false);
      return result;
    },
    [call],
  );

  return { state, busy, error, load, start, answer, submit, retake };
}
