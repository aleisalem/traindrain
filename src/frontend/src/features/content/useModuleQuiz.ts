import { useCallback, useEffect, useState } from "react";

import type { QuestionDraft, QuizBody, QuizSettings, TryoutResult } from "./types";
import { SCHEMA_VERSION } from "../../content/schema";

export type ModuleQuizState = {
  quiz: QuizBody | null;
  loading: boolean;
  loadError: boolean;
  busy: boolean;
  /** An i18n key under `quiz.`, or null. */
  error: string | null;
  createQuiz: () => Promise<boolean>;
  saveSettings: (settings: QuizSettings) => Promise<boolean>;
  removeQuiz: () => Promise<boolean>;
  addQuestion: (draft: QuestionDraft) => Promise<boolean>;
  updateQuestion: (id: string, draft: QuestionDraft) => Promise<boolean>;
  deleteQuestion: (id: string) => Promise<boolean>;
  moveQuestion: (id: string, offset: number) => Promise<boolean>;
  tryout: (answers: Record<string, string[]>) => Promise<TryoutResult | null>;
  clearError: () => void;
};

const DEFAULT_SETTINGS: QuizSettings = {
  pass_mark_percent: 80,
  max_attempts: null,
  shuffle: false,
  reveal_after_pass: false,
};

/** The one owner of a module's draft-quiz state; every write returns the fresh quiz. */
export function useModuleQuiz(moduleId: string): ModuleQuizState {
  const base = `/api/content/modules/${moduleId}/quiz`;
  const [quiz, setQuiz] = useState<QuizBody | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const response = await fetch(base);
        if (cancelled) return;
        if (!response.ok) {
          setLoadError(true);
        } else {
          setQuiz((await response.json()) as QuizBody | null);
        }
      } catch {
        if (!cancelled) setLoadError(true);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [base]);

  const send = useCallback(
    async (path: string, method: string, body?: unknown): Promise<Response | null> => {
      setBusy(true);
      setError(null);
      try {
        const response = await fetch(path, {
          method,
          headers: { "Content-Type": "application/json" },
          body: body === undefined ? undefined : JSON.stringify(body),
        });
        if (!response.ok) {
          setError(response.status === 422 ? "error_rejected" : "error_unknown");
          return null;
        }
        return response;
      } catch {
        setError("error_unknown");
        return null;
      } finally {
        setBusy(false);
      }
    },
    [],
  );

  /** Send a write whose response is the fresh quiz, and adopt it. */
  const write = useCallback(
    async (path: string, method: string, body?: unknown): Promise<boolean> => {
      const response = await send(path, method, body);
      if (!response) return false;
      setQuiz((await response.json()) as QuizBody);
      return true;
    },
    [send],
  );

  const payload = (draft: QuestionDraft) => ({
    type: draft.type,
    schema_version: SCHEMA_VERSION,
    prompt: draft.prompt,
    explanation: draft.explanation,
    options: draft.options,
  });

  return {
    quiz,
    loading,
    loadError,
    busy,
    error,
    createQuiz: () => write(base, "PUT", DEFAULT_SETTINGS),
    saveSettings: (settings) => write(base, "PUT", settings),
    removeQuiz: async () => {
      const response = await send(base, "DELETE");
      if (response) setQuiz(null);
      return response !== null;
    },
    addQuestion: (draft) => write(`${base}/questions`, "POST", payload(draft)),
    updateQuestion: (id, draft) => write(`${base}/questions/${id}`, "PATCH", payload(draft)),
    deleteQuestion: (id) => write(`${base}/questions/${id}`, "DELETE"),
    moveQuestion: async (id, offset) => {
      if (!quiz) return false;
      const order = quiz.questions.map((question) => question.id);
      const from = order.indexOf(id);
      const to = from + offset;
      if (from < 0 || to < 0 || to >= order.length) return false;
      order.splice(to, 0, ...order.splice(from, 1));
      return write(`${base}/questions/reorder`, "POST", { question_ids: order });
    },
    tryout: async (answers) => {
      const response = await send(`${base}/tryout`, "POST", { answers });
      return response ? ((await response.json()) as TryoutResult) : null;
    },
    clearError: () => setError(null),
  };
}
