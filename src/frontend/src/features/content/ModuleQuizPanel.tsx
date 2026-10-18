import { useState } from "react";
import { useTranslation } from "react-i18next";

import { PagePreview } from "./PagePreview";
import { QuizQuestionForm } from "./QuizQuestionForm";
import { QuizTryout } from "./QuizTryout";
import type { QuestionType, QuizProblem, QuizSettings } from "./types";
import type { ModuleAssetsState } from "./useModuleAssets";
import { useModuleQuiz } from "./useModuleQuiz";

type Props = {
  moduleId: string;
  /** Shared with the page editor so prompts can embed the module's images. */
  assets: ModuleAssetsState;
};

const pillClassName =
  "rounded-full border border-border bg-bg-elevated px-4 py-1.5 text-sm font-medium transition hover:-translate-y-0.5 hover:shadow-[var(--shadow)] disabled:opacity-60 disabled:hover:translate-y-0";

const QUESTION_TYPES: QuestionType[] = ["single_choice", "multiple_choice", "true_false"];

type Editing = { questionId: string | null; type: QuestionType };

/**
 * The quiz section of the module authoring screen.
 *
 * Everything here edits the draft; publishing validates it and freezes a copy
 * into the version. The panel shows what would block a publish as it stands, so
 * the author is never surprised by a refusal.
 */
export function ModuleQuizPanel({ moduleId, assets }: Props) {
  const { t } = useTranslation();
  const state = useModuleQuiz(moduleId);
  const { quiz } = state;
  const [editing, setEditing] = useState<Editing | null>(null);
  const [tryingOut, setTryingOut] = useState(false);
  const [confirmingRemove, setConfirmingRemove] = useState(false);
  // Unsaved edits laid over the stored settings; cleared on a successful save.
  const [edits, setEdits] = useState<QuizSettings | null>(null);
  const [savedSettings, setSavedSettings] = useState(false);

  if (state.loading) return null;
  if (state.loadError) {
    return (
      <section className="flex flex-col gap-3">
        <h3 className="text-lg font-medium">{t("quiz.heading")}</h3>
        <p role="alert" className="text-sm text-danger">
          {t("content.load_error")}
        </p>
      </section>
    );
  }

  const settings: QuizSettings | null = quiz
    ? (edits ?? {
        pass_mark_percent: quiz.pass_mark_percent,
        max_attempts: quiz.max_attempts,
        shuffle: quiz.shuffle,
        reveal_after_pass: quiz.reveal_after_pass,
      })
    : null;
  const setSettings = setEdits;

  const library = {
    images: assets.images,
    upload: (file: File) => assets.upload("image", file),
    busy: assets.busy,
  };

  function describe(problem: QuizProblem): string {
    const index = quiz?.questions.findIndex((q) => q.id === problem.question_id) ?? -1;
    return t(`quiz.problem_${problem.code}`, {
      number: index + 1,
      defaultValue: problem.message,
    });
  }

  return (
    <section className="flex flex-col gap-4" aria-labelledby="quiz-heading">
      <div>
        <h3 id="quiz-heading" className="text-lg font-medium">
          {t("quiz.heading")}
        </h3>
        <p className="text-sm text-fg-muted">{t("quiz.description")}</p>
      </div>

      {state.error && (
        <p role="alert" className="text-sm text-danger">
          {t(`quiz.${state.error}`)}
        </p>
      )}

      {quiz === null || settings === null ? (
        <div className="flex flex-col items-start gap-2">
          <p className="text-sm text-fg-muted">{t("quiz.none")}</p>
          <button
            type="button"
            disabled={state.busy}
            onClick={() => void state.createQuiz()}
            className={pillClassName}
          >
            {t("quiz.add_quiz")}
          </button>
        </div>
      ) : (
        <>
          <form
            aria-label={t("quiz.settings_label")}
            onSubmit={async (event) => {
              event.preventDefault();
              const ok = await state.saveSettings(settings);
              setSavedSettings(ok);
              if (ok) setEdits(null);
            }}
            className="grid gap-3 rounded-2xl border border-border bg-bg-elevated p-4 shadow-[var(--shadow)] sm:grid-cols-2"
          >
            <label className="flex flex-col gap-1 text-sm">
              {t("quiz.pass_mark")}
              <input
                type="number"
                min={1}
                max={100}
                value={settings.pass_mark_percent}
                onChange={(event) =>
                  setSettings({ ...settings, pass_mark_percent: Number(event.target.value) })
                }
                className="rounded-xl border border-border bg-bg px-3 py-1.5 focus:border-primary focus:outline-none"
              />
            </label>
            <div className="flex flex-col gap-1 text-sm">
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={settings.max_attempts !== null}
                  onChange={(event) =>
                    setSettings({ ...settings, max_attempts: event.target.checked ? 3 : null })
                  }
                />
                {t("quiz.limit_attempts")}
              </label>
              {settings.max_attempts !== null && (
                <input
                  type="number"
                  min={1}
                  max={100}
                  aria-label={t("quiz.max_attempts")}
                  value={settings.max_attempts}
                  onChange={(event) =>
                    setSettings({ ...settings, max_attempts: Number(event.target.value) })
                  }
                  className="rounded-xl border border-border bg-bg px-3 py-1.5 focus:border-primary focus:outline-none"
                />
              )}
            </div>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={settings.shuffle}
                onChange={(event) => setSettings({ ...settings, shuffle: event.target.checked })}
              />
              {t("quiz.shuffle")}
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={settings.reveal_after_pass}
                onChange={(event) =>
                  setSettings({ ...settings, reveal_after_pass: event.target.checked })
                }
              />
              {t("quiz.reveal_after_pass")}
            </label>
            <div className="flex flex-wrap items-center gap-3 sm:col-span-2">
              <button type="submit" disabled={state.busy} className={pillClassName}>
                {t("quiz.save_settings")}
              </button>
              {savedSettings && (
                <span role="status" className="text-sm text-success">
                  {t("quiz.settings_saved")}
                </span>
              )}
            </div>
          </form>

          {quiz.problems.length > 0 && (
            <div role="status" className="rounded-xl border border-warning/40 bg-warning/10 px-4 py-3 text-sm text-warning">
              <p className="font-medium">{t("quiz.problems_heading")}</p>
              <ul className="list-disc pl-5">
                {quiz.problems.map((problem, index) => (
                  <li key={`${problem.code}-${problem.question_id}-${index}`}>{describe(problem)}</li>
                ))}
              </ul>
            </div>
          )}

          {quiz.questions.length > 0 && (
            <ol className="flex flex-col gap-3">
              {quiz.questions.map((question, index) => (
                <li
                  key={question.id}
                  className="flex flex-col gap-2 rounded-2xl border border-border bg-bg-elevated p-4"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="text-xs uppercase tracking-wide text-fg-muted">
                      {t("quiz.question_number", { number: index + 1 })} ·{" "}
                      {t(`quiz.type_${question.type}`)}
                    </p>
                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        disabled={state.busy || index === 0}
                        aria-label={t("quiz.move_up", { number: index + 1 })}
                        onClick={() => void state.moveQuestion(question.id, -1)}
                        className="rounded-full border border-border px-2 py-0.5 text-xs disabled:opacity-40"
                      >
                        ↑
                      </button>
                      <button
                        type="button"
                        disabled={state.busy || index === quiz.questions.length - 1}
                        aria-label={t("quiz.move_down", { number: index + 1 })}
                        onClick={() => void state.moveQuestion(question.id, 1)}
                        className="rounded-full border border-border px-2 py-0.5 text-xs disabled:opacity-40"
                      >
                        ↓
                      </button>
                      <button
                        type="button"
                        onClick={() => setEditing({ questionId: question.id, type: question.type })}
                        aria-label={t("quiz.edit_question", { number: index + 1 })}
                        className={pillClassName}
                      >
                        {t("quiz.edit")}
                      </button>
                      <button
                        type="button"
                        disabled={state.busy}
                        aria-label={t("quiz.delete_question", { number: index + 1 })}
                        onClick={() => void state.deleteQuestion(question.id)}
                        className="rounded-full border border-danger px-3 py-1 text-xs text-danger disabled:opacity-40"
                      >
                        {t("quiz.delete")}
                      </button>
                    </div>
                  </div>
                  <PagePreview document={question.prompt} />
                  <ul className="flex flex-col gap-1 text-sm">
                    {question.options.map((option) => (
                      <li key={option.id} className={option.is_correct ? "font-medium text-success" : ""}>
                        {option.is_correct ? "✓ " : "○ "}
                        {question.type === "true_false" ? t(`quiz.${option.text}`) : option.text}
                      </li>
                    ))}
                  </ul>
                </li>
              ))}
            </ol>
          )}

          {editing ? (
            <QuizQuestionForm
              // Remount per question so one question's buffer never leaks into another.
              key={editing.questionId ?? `new-${editing.type}`}
              question={quiz.questions.find((q) => q.id === editing.questionId) ?? null}
              type={editing.type}
              library={library}
              busy={state.busy}
              onCancel={() => setEditing(null)}
              onSave={async (draft) => {
                const ok = editing.questionId
                  ? await state.updateQuestion(editing.questionId, draft)
                  : await state.addQuestion(draft);
                if (ok) setEditing(null);
              }}
            />
          ) : (
            <div className="flex flex-wrap gap-2" role="group" aria-label={t("quiz.add_question")}>
              {QUESTION_TYPES.map((type) => (
                <button
                  key={type}
                  type="button"
                  onClick={() => {
                    setTryingOut(false);
                    setEditing({ questionId: null, type });
                  }}
                  className={pillClassName}
                >
                  {t("quiz.add_type", { type: t(`quiz.type_${type}`) })}
                </button>
              ))}
            </div>
          )}

          {tryingOut && quiz.questions.length > 0 && (
            <QuizTryout
              quiz={quiz}
              busy={state.busy}
              onSubmit={state.tryout}
              onClose={() => setTryingOut(false)}
            />
          )}

          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              disabled={quiz.questions.length === 0}
              aria-pressed={tryingOut}
              onClick={() => setTryingOut((current) => !current)}
              className={pillClassName}
            >
              {t("quiz.tryout")}
            </button>
            {confirmingRemove ? (
              <>
                <span className="text-sm text-fg-muted">{t("quiz.remove_confirm")}</span>
                <button
                  type="button"
                  disabled={state.busy}
                  onClick={async () => {
                    if (await state.removeQuiz()) {
                      setConfirmingRemove(false);
                      setEditing(null);
                      setTryingOut(false);
                    }
                  }}
                  className="rounded-full border border-danger px-4 py-1.5 text-sm font-medium text-danger"
                >
                  {t("quiz.remove_yes")}
                </button>
                <button type="button" onClick={() => setConfirmingRemove(false)} className={pillClassName}>
                  {t("quiz.cancel")}
                </button>
              </>
            ) : (
              <button
                type="button"
                onClick={() => setConfirmingRemove(true)}
                className="rounded-full border border-danger px-4 py-1.5 text-sm font-medium text-danger"
              >
                {t("quiz.remove")}
              </button>
            )}
          </div>
        </>
      )}
    </section>
  );
}
