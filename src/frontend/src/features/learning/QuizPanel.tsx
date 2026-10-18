import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { PagePreview } from "../content/PagePreview";
import type { Attempt, AttemptQuestion, QuizState, QuizSummary } from "./types";
import { useQuizAttempt } from "./useQuizAttempt";

type Props = {
  groupId: string;
  summary: QuizSummary;
  /** Every page has been viewed — the quiz opens only then. */
  pagesDone: boolean;
  onSummary: (summary: QuizSummary) => void;
  /** The learner chose to re-read: the viewer clears its page progress. */
  onReread: () => void;
};

const pillClassName =
  "rounded-full border border-border bg-bg-elevated px-4 py-2 text-sm font-medium transition hover:-translate-y-0.5 hover:shadow-[var(--shadow)] disabled:opacity-50 disabled:hover:translate-y-0";
const primaryClassName =
  "rounded-full bg-[image:var(--gradient)] px-5 py-2.5 text-sm font-semibold text-primary-fg transition hover:-translate-y-0.5 hover:shadow-[var(--shadow)] disabled:opacity-50 disabled:hover:translate-y-0";

const CONFETTI = ["bg-primary", "bg-success", "bg-warning", "bg-danger"];

function Confetti() {
  // Decorative only (aria-hidden), and hidden outright under reduced motion.
  return (
    <div aria-hidden="true" className="pointer-events-none absolute inset-x-0 top-0 h-32 overflow-hidden">
      {Array.from({ length: 18 }, (_, i) => (
        <span
          key={i}
          className={`confetti-piece absolute h-2 w-2 rounded-sm ${CONFETTI[i % CONFETTI.length]}`}
          style={{ left: `${(i * 37) % 100}%`, animationDelay: `${(i % 6) * 90}ms` }}
        />
      ))}
    </div>
  );
}

/**
 * The quiz, as a learner takes it: one question at a time, answers saved as they
 * are chosen (so closing the tab loses nothing), graded on the server.
 *
 * Accessibility: each question is a fieldset with a legend; focus moves to the
 * question's heading on every step and to the result heading on submission; the
 * position and the outcome are announced through a live region.
 */
export function QuizPanel({ groupId, summary, pagesDone, onSummary, onReread }: Props) {
  const { t } = useTranslation();
  const quiz = useQuizAttempt(groupId);
  const [loaded, setLoaded] = useState(false);
  const [step, setStep] = useState(0);
  const [announcement, setAnnouncement] = useState("");
  const headingRef = useRef<HTMLHeadingElement>(null);
  const resultRef = useRef<HTMLHeadingElement>(null);
  const moved = useRef(false);

  const { load, state } = quiz;
  useEffect(() => {
    if (!pagesDone) return;
    void load().then(() => setLoaded(true));
  }, [pagesDone, load]);

  const attempt: Attempt | null = state?.attempt ?? null;
  const taking = attempt !== null && attempt.submitted_at === null;
  const result = attempt?.result ?? null;

  useEffect(() => {
    if (state) onSummary(state.summary);
  }, [state, onSummary]);

  useEffect(() => {
    if (moved.current) headingRef.current?.focus();
  }, [step]);

  useEffect(() => {
    if (result) resultRef.current?.focus();
  }, [result]);

  if (!pagesDone) {
    return (
      <section className="rounded-2xl border border-border bg-bg-elevated p-5 shadow-[var(--shadow)]">
        <h3 className="text-lg font-medium">{t("quiz_taking.heading")}</h3>
        <p className="text-sm text-fg-muted">{t("quiz_taking.locked_hint")}</p>
      </section>
    );
  }

  function adopt(next: QuizState | null) {
    if (next) {
      setStep(0);
      moved.current = false;
    }
  }

  async function choose(question: AttemptQuestion, optionId: string, checked: boolean) {
    if (!attempt) return;
    const existing = attempt.answers[question.id] ?? [];
    const next =
      question.type === "multiple_choice"
        ? checked
          ? [...existing, optionId]
          : existing.filter((id) => id !== optionId)
        : [optionId];
    await quiz.answer(attempt.id, question.id, next);
  }

  const errorText = quiz.error ? t(`quiz_taking.error_${quiz.error}`) : null;
  const current = state?.summary ?? summary;
  const attemptsText =
    current.attempts_remaining === null
      ? t("quiz_taking.attempts_unlimited")
      : t("quiz_taking.attempts_remaining", { count: current.attempts_remaining });

  return (
    <section
      aria-labelledby="quiz-heading"
      className="relative flex flex-col gap-4 overflow-hidden rounded-2xl border border-border bg-bg-elevated p-5 shadow-[var(--shadow)] sm:p-7"
    >
      <h3 id="quiz-heading" className="text-lg font-medium">
        {t("quiz_taking.heading")}
      </h3>
      <p role="status" aria-live="polite" className="sr-only">
        {announcement}
      </p>
      {errorText && (
        <p role="alert" className="text-sm text-danger">
          {errorText}
        </p>
      )}

      {loaded && !taking && !result && (
        <div className="flex flex-col items-start gap-3">
          {current.passed ? (
            <p className="text-sm text-success">
              {t("quiz_taking.passed_badge", { score: current.best_score_percent ?? 0 })}
            </p>
          ) : current.exhausted ? (
            <p role="alert" className="text-sm text-danger">
              {t("quiz_taking.exhausted")}
            </p>
          ) : (
            <>
              <p className="text-sm text-fg-muted">
                {t("quiz_taking.intro", { count: current.question_count, mark: current.pass_mark_percent })}
              </p>
              <p className="text-sm text-fg-muted">{attemptsText}</p>
              <button
                type="button"
                disabled={quiz.busy}
                className={primaryClassName}
                onClick={async () => adopt(await quiz.start())}
              >
                {quiz.busy ? t("quiz_taking.starting") : t("quiz_taking.start")}
              </button>
            </>
          )}
        </div>
      )}

      {taking && attempt && (
        <Question
          attempt={attempt}
          step={step}
          busy={quiz.busy}
          headingRef={headingRef}
          onChoose={choose}
          onStep={(next) => {
            moved.current = true;
            setStep(next);
            setAnnouncement(
              t("quiz_taking.question_position", {
                position: next + 1,
                total: attempt.questions.length,
              }),
            );
          }}
          onSubmit={async () => {
            const next = await quiz.submit(attempt.id);
            const outcome = next?.attempt?.result;
            if (outcome) {
              setAnnouncement(
                t(
                  outcome.passed
                    ? "quiz_taking.result_announce_passed"
                    : "quiz_taking.result_announce_failed",
                  { score: outcome.score_percent },
                ),
              );
            }
          }}
        />
      )}

      {!taking && attempt && result && (
        <Result
          attempt={attempt}
          summary={current}
          resultRef={resultRef}
          busy={quiz.busy}
          onRetakeQuiz={async () => adopt(await quiz.retake("quiz"))}
          onRetakeModule={async () => {
            if (await quiz.retake("module")) onReread();
          }}
        />
      )}
    </section>
  );
}

function Question({
  attempt,
  step,
  busy,
  headingRef,
  onChoose,
  onStep,
  onSubmit,
}: {
  attempt: Attempt;
  step: number;
  busy: boolean;
  headingRef: React.RefObject<HTMLHeadingElement | null>;
  onChoose: (question: AttemptQuestion, optionId: string, checked: boolean) => Promise<void>;
  onStep: (next: number) => void;
  onSubmit: () => Promise<void>;
}) {
  const { t } = useTranslation();
  const total = attempt.questions.length;
  const question = attempt.questions[step];
  const multiple = question.type === "multiple_choice";
  const answered = attempt.questions.filter((q) => (attempt.answers[q.id] ?? []).length > 0).length;
  const last = step === total - 1;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <div
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={total}
          aria-valuenow={answered}
          aria-label={t("quiz_taking.answer_progress", { answered, total })}
          className="h-2 w-full overflow-hidden rounded-full bg-bg-subtle"
        >
          <div
            className="h-full rounded-full bg-[image:var(--gradient)] transition-[width]"
            style={{ width: `${(answered / total) * 100}%` }}
          />
        </div>
        <p className="text-sm text-fg-muted">{t("quiz_taking.answer_progress", { answered, total })}</p>
      </div>

      <fieldset key={question.id} className="flex flex-col gap-3">
        <legend className="sr-only">{t("quiz_taking.question_position", { position: step + 1, total })}</legend>
        <h4
          ref={headingRef}
          tabIndex={-1}
          className="text-base font-semibold outline-none focus-visible:ring-2 focus-visible:ring-primary"
        >
          {t("quiz_taking.question_position", { position: step + 1, total })}
        </h4>
        <PagePreview document={question.prompt} />
        <p className="text-sm text-fg-muted">
          {multiple ? t("quiz_taking.choose_many") : t("quiz_taking.choose_one")}
        </p>
        {question.options.map((option) => {
          const checked = (attempt.answers[question.id] ?? []).includes(option.id);
          return (
            <label
              key={option.id}
              className={`flex cursor-pointer items-center gap-3 rounded-2xl border px-4 py-3 text-sm transition focus-within:ring-2 focus-within:ring-primary ${
                checked ? "border-primary bg-primary/10" : "border-border bg-bg"
              }`}
            >
              <input
                type={multiple ? "checkbox" : "radio"}
                name={question.id}
                checked={checked}
                onChange={(event) => void onChoose(question, option.id, event.target.checked)}
              />
              {question.type === "true_false" ? t(`quiz_taking.${option.text}`) : option.text}
            </label>
          );
        })}
      </fieldset>

      {last && answered < total && (
        <p className="text-sm text-warning">
          {t("quiz_taking.unanswered_warning", { count: total - answered })}
        </p>
      )}

      <div className="flex flex-wrap items-center justify-between gap-3">
        <button type="button" disabled={step === 0} onClick={() => onStep(step - 1)} className={pillClassName}>
          {t("quiz_taking.previous")}
        </button>
        {last ? (
          <button type="button" disabled={busy} onClick={() => void onSubmit()} className={primaryClassName}>
            {busy ? t("quiz_taking.submitting") : t("quiz_taking.submit")}
          </button>
        ) : (
          <button type="button" onClick={() => onStep(step + 1)} className={pillClassName}>
            {t("quiz_taking.next")}
          </button>
        )}
      </div>
    </div>
  );
}

function Result({
  attempt,
  summary,
  resultRef,
  busy,
  onRetakeQuiz,
  onRetakeModule,
}: {
  attempt: Attempt;
  summary: QuizSummary;
  resultRef: React.RefObject<HTMLHeadingElement | null>;
  busy: boolean;
  onRetakeQuiz: () => Promise<void>;
  onRetakeModule: () => Promise<void>;
}) {
  const { t } = useTranslation();
  const result = attempt.result!;
  const revealed = new Map((result.revealed ?? []).map((entry) => [entry.question_id, entry]));

  return (
    <div className="flex flex-col gap-4">
      {result.passed && <Confetti />}
      <h4
        ref={resultRef}
        tabIndex={-1}
        className={`text-2xl font-bold outline-none focus-visible:ring-2 focus-visible:ring-primary ${
          result.passed ? "text-success" : "text-danger"
        }`}
      >
        {result.passed ? t("quiz_taking.result_passed") : t("quiz_taking.result_failed")}
      </h4>
      <p className="text-sm">
        {t("quiz_taking.result_score", {
          score: result.score_percent,
          correct: result.correct_count,
          total: result.total,
          mark: result.pass_mark_percent,
        })}
      </p>
      {result.passed && <p className="text-sm text-fg-muted">{t("quiz_taking.passed_unlocks")}</p>}

      <h5 className="text-sm font-semibold">{t("quiz_taking.review_heading")}</h5>
      <ol className="flex flex-col gap-3">
        {attempt.questions.map((question, index) => {
          const outcome = result.questions.find((entry) => entry.question_id === question.id);
          const reveal = revealed.get(question.id);
          return (
            <li key={question.id} className="flex flex-col gap-1 rounded-2xl border border-border p-3 text-sm">
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium">
                  {t("quiz_taking.question_position", { position: index + 1, total: attempt.questions.length })}
                </span>
                {/* Icon + words, never colour alone (colour-blind theme). */}
                <span className={outcome?.correct ? "text-success" : "text-danger"}>
                  {outcome?.correct ? "✓ " : "✗ "}
                  {outcome?.correct ? t("quiz_taking.question_correct") : t("quiz_taking.question_wrong")}
                </span>
              </div>
              {reveal && (
                <>
                  <p className="text-fg-muted">
                    {t("quiz_taking.correct_answer")}:{" "}
                    {question.options
                      .filter((option) => reveal.correct_option_ids.includes(option.id))
                      .map((option) =>
                        question.type === "true_false" ? t(`quiz_taking.${option.text}`) : option.text,
                      )
                      .join(", ")}
                  </p>
                  {reveal.explanation && (
                    <div>
                      <p className="font-medium">{t("quiz_taking.explanation")}</p>
                      <PagePreview document={reveal.explanation} />
                    </div>
                  )}
                </>
              )}
            </li>
          );
        })}
      </ol>

      {!result.passed &&
        (summary.exhausted ? (
          <p role="alert" className="text-sm text-danger">
            {t("quiz_taking.exhausted")}
          </p>
        ) : (
          <div className="flex flex-col items-start gap-3">
            <p className="text-sm font-medium">{t("quiz_taking.retake_heading")}</p>
            <p className="text-sm text-fg-muted">
              {summary.attempts_remaining === null
                ? t("quiz_taking.attempts_unlimited")
                : t("quiz_taking.attempts_remaining", { count: summary.attempts_remaining })}
            </p>
            <div className="flex flex-wrap gap-3">
              <button type="button" disabled={busy} onClick={() => void onRetakeQuiz()} className={primaryClassName}>
                {t("quiz_taking.retake_quiz")}
              </button>
              <button type="button" disabled={busy} onClick={() => void onRetakeModule()} className={pillClassName}>
                {t("quiz_taking.retake_module")}
              </button>
            </div>
          </div>
        ))}
    </div>
  );
}
