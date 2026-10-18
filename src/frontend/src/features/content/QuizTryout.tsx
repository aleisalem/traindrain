import { useState } from "react";
import { useTranslation } from "react-i18next";

import { PagePreview } from "./PagePreview";
import type { QuizBody, TryoutResult } from "./types";

type Props = {
  quiz: QuizBody;
  busy: boolean;
  onSubmit: (answers: Record<string, string[]>) => Promise<TryoutResult | null>;
  onClose: () => void;
};

/**
 * Take the draft quiz as a learner would. The answers go to the server to be
 * graded and nothing is recorded: no attempt, no progress.
 */
export function QuizTryout({ quiz, busy, onSubmit, onClose }: Props) {
  const { t } = useTranslation();
  const [answers, setAnswers] = useState<Record<string, string[]>>({});
  const [result, setResult] = useState<TryoutResult | null>(null);

  function choose(questionId: string, optionId: string, multiple: boolean, checked: boolean) {
    setResult(null);
    setAnswers((current) => {
      const existing = current[questionId] ?? [];
      const next = multiple
        ? checked
          ? [...existing, optionId]
          : existing.filter((id) => id !== optionId)
        : [optionId];
      return { ...current, [questionId]: next };
    });
  }

  return (
    <form
      aria-label={t("quiz.tryout_label")}
      onSubmit={async (event) => {
        event.preventDefault();
        setResult(await onSubmit(answers));
      }}
      className="flex flex-col gap-4 rounded-2xl border border-border bg-bg-elevated p-4 shadow-[var(--shadow)]"
    >
      <p className="text-sm text-fg-muted">{t("quiz.tryout_hint")}</p>

      {quiz.questions.map((question, index) => {
        const multiple = question.type === "multiple_choice";
        const graded = result?.questions.find((entry) => entry.question_id === question.id);
        return (
          <fieldset key={question.id} className="flex flex-col gap-2">
            <legend className="pb-1 text-sm font-semibold">
              {t("quiz.question_number", { number: index + 1 })}
            </legend>
            <PagePreview document={question.prompt} />
            {question.options.map((option) => (
              <label key={option.id} className="flex items-center gap-2 text-sm">
                <input
                  type={multiple ? "checkbox" : "radio"}
                  name={question.id}
                  checked={(answers[question.id] ?? []).includes(option.id)}
                  onChange={(event) =>
                    choose(question.id, option.id, multiple, event.target.checked)
                  }
                />
                {question.type === "true_false" ? t(`quiz.${option.text}`) : option.text}
              </label>
            ))}
            {graded && (
              <p
                className={graded.correct ? "text-sm text-success" : "text-sm text-danger"}
              >
                {graded.correct ? t("quiz.tryout_correct") : t("quiz.tryout_wrong")}
              </p>
            )}
            {graded && question.explanation && <PagePreview document={question.explanation} />}
          </fieldset>
        );
      })}

      {/* Announced when it appears, because the result is the point. */}
      <div role="status" aria-live="polite">
        {result && (
          <p className={result.passed ? "font-semibold text-success" : "font-semibold text-danger"}>
            {t("quiz.tryout_score", {
              correct: result.correct_count,
              total: result.total,
              percent: result.score_percent,
            })}{" "}
            {result.passed
              ? t("quiz.tryout_passed", { mark: result.pass_mark_percent })
              : t("quiz.tryout_failed", { mark: result.pass_mark_percent })}
          </p>
        )}
      </div>

      <div className="flex flex-wrap justify-end gap-2">
        <button
          type="button"
          onClick={onClose}
          className="rounded-full border border-border bg-bg-elevated px-4 py-1.5 text-sm font-medium"
        >
          {t("quiz.tryout_close")}
        </button>
        <button
          type="submit"
          disabled={busy}
          className="rounded-full bg-[image:var(--gradient)] px-5 py-2 text-sm font-semibold text-primary-fg disabled:opacity-60"
        >
          {t("quiz.tryout_submit")}
        </button>
      </div>
    </form>
  );
}
