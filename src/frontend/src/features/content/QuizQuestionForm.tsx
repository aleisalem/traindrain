import { useState } from "react";
import { useTranslation } from "react-i18next";

import { emptyDocument, type PageDocument } from "../../content/schema";
import { PageEditor, type ImageLibrary } from "./PageEditor";
import type { QuestionDraft, QuestionType, QuizQuestion } from "./types";

type Props = {
  /** The question being edited, or null for a new one of `type`. */
  question: QuizQuestion | null;
  type: QuestionType;
  library: ImageLibrary;
  busy: boolean;
  onSave: (draft: QuestionDraft) => void;
  onCancel: () => void;
};

type OptionRow = { key: number; text: string; is_correct: boolean };

const pillClassName =
  "rounded-full border border-border bg-bg-elevated px-4 py-1.5 text-sm font-medium transition hover:-translate-y-0.5 hover:shadow-[var(--shadow)] disabled:opacity-60 disabled:hover:translate-y-0";

const MAX_OPTIONS = 10;

function initialOptions(question: QuizQuestion | null, type: QuestionType): OptionRow[] {
  if (type === "true_false") {
    return ["true", "false"].map((text, key) => ({
      key,
      text,
      is_correct: question?.options.find((option) => option.text === text)?.is_correct ?? false,
    }));
  }
  if (question) {
    return question.options.map((option, key) => ({
      key,
      text: option.text,
      is_correct: option.is_correct,
    }));
  }
  return [0, 1].map((key) => ({ key, text: "", is_correct: false }));
}

/**
 * Edit one question: a rich-text prompt, its answer options with the correct
 * ones marked, and an optional explanation. Correctness is chosen with radios
 * for single-choice and true/false (so "exactly one" cannot be violated here)
 * and checkboxes for multiple-choice.
 */
export function QuizQuestionForm({ question, type, library, busy, onSave, onCancel }: Props) {
  const { t } = useTranslation();
  const [prompt, setPrompt] = useState<PageDocument>(question?.prompt ?? emptyDocument());
  const [explanation, setExplanation] = useState<PageDocument | null>(
    question?.explanation ?? null,
  );
  const [options, setOptions] = useState<OptionRow[]>(() => initialOptions(question, type));
  const [nextKey, setNextKey] = useState(options.length);
  const fixed = type === "true_false";

  function setCorrect(key: number, checked: boolean) {
    setOptions((rows) =>
      rows.map((row) =>
        type === "multiple_choice"
          ? row.key === key
            ? { ...row, is_correct: checked }
            : row
          : { ...row, is_correct: row.key === key },
      ),
    );
  }

  return (
    <form
      aria-label={t("quiz.question_form_label")}
      onSubmit={(event) => {
        event.preventDefault();
        onSave({
          type,
          prompt,
          explanation,
          options: options.map(({ text, is_correct }) => ({ text, is_correct })),
        });
      }}
      className="flex flex-col gap-4 rounded-2xl border border-border bg-bg-elevated p-4 shadow-[var(--shadow)]"
    >
      <h4 className="font-semibold">{t(`quiz.type_${type}`)}</h4>

      <div className="flex flex-col gap-1 text-sm">
        <span className="font-medium">{t("quiz.prompt_label")}</span>
        <PageEditor document={prompt} onChange={setPrompt} library={library} />
      </div>

      <fieldset className="flex flex-col gap-2">
        <legend className="pb-1 text-sm font-medium">{t("quiz.options_legend")}</legend>
        <p className="text-xs text-fg-muted">
          {t(type === "multiple_choice" ? "quiz.options_hint_multiple" : "quiz.options_hint_single")}
        </p>
        {options.map((row, index) => (
          <div key={row.key} className="flex flex-wrap items-center gap-2">
            <input
              type={type === "multiple_choice" ? "checkbox" : "radio"}
              name="correct-option"
              checked={row.is_correct}
              aria-label={t("quiz.mark_correct", { number: index + 1 })}
              onChange={(event) => setCorrect(row.key, event.target.checked)}
            />
            {fixed ? (
              <span className="text-sm">{t(`quiz.${row.text}`)}</span>
            ) : (
              <>
                <input
                  type="text"
                  value={row.text}
                  maxLength={500}
                  aria-label={t("quiz.option_label", { number: index + 1 })}
                  onChange={(event) =>
                    setOptions((rows) =>
                      rows.map((other) =>
                        other.key === row.key ? { ...other, text: event.target.value } : other,
                      ),
                    )
                  }
                  className="min-w-0 flex-1 rounded-xl border border-border bg-bg px-3 py-1.5 text-sm focus:border-primary focus:outline-none"
                />
                <button
                  type="button"
                  disabled={options.length <= 2}
                  aria-label={t("quiz.remove_option", { number: index + 1 })}
                  onClick={() => setOptions((rows) => rows.filter((other) => other.key !== row.key))}
                  className="rounded-full border border-danger px-2 py-0.5 text-xs text-danger disabled:opacity-40"
                >
                  ×
                </button>
              </>
            )}
          </div>
        ))}
        {!fixed && (
          <div>
            <button
              type="button"
              disabled={options.length >= MAX_OPTIONS}
              onClick={() => {
                setOptions((rows) => [...rows, { key: nextKey, text: "", is_correct: false }]);
                setNextKey((key) => key + 1);
              }}
              className={pillClassName}
            >
              {t("quiz.add_option")}
            </button>
          </div>
        )}
      </fieldset>

      <div className="flex flex-col gap-2 text-sm">
        {explanation === null ? (
          <div>
            <button
              type="button"
              onClick={() => setExplanation(emptyDocument())}
              className={pillClassName}
            >
              {t("quiz.add_explanation")}
            </button>
          </div>
        ) : (
          <>
            <span className="font-medium">{t("quiz.explanation_label")}</span>
            <PageEditor document={explanation} onChange={setExplanation} library={library} />
            <div>
              <button type="button" onClick={() => setExplanation(null)} className={pillClassName}>
                {t("quiz.remove_explanation")}
              </button>
            </div>
          </>
        )}
      </div>

      <div className="flex flex-wrap justify-end gap-2">
        <button type="button" onClick={onCancel} className={pillClassName}>
          {t("quiz.cancel")}
        </button>
        <button
          type="submit"
          disabled={busy}
          className="rounded-full bg-[image:var(--gradient)] px-5 py-2 text-sm font-semibold text-primary-fg transition hover:-translate-y-0.5 hover:shadow-[var(--shadow)] disabled:opacity-60 disabled:hover:translate-y-0"
        >
          {t("quiz.save_question")}
        </button>
      </div>
    </form>
  );
}
