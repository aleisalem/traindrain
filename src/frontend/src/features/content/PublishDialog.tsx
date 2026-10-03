import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { ModalDialog } from "./ModalDialog";
import type { RevisionImpact, RevisionKind } from "./types";

type Props = {
  moduleId: string;
  /** A first publish reads differently from a revision, so the copy differs. */
  republish: boolean;
  onConfirm: (kind: RevisionKind) => void;
  onCancel: () => void;
};

/**
 * The one question a publish cannot dodge.
 *
 * Neither radio starts selected and the confirming button stays disabled until
 * one is: whether a revision drags every completed learner back through the
 * module is the author's decision, and a pre-checked default would be the
 * screen making it for them while looking like it asked.
 *
 * Choosing `substantive` names how many people it affects. "Everyone who
 * completed this will have to read it again" is an abstraction until it says
 * how many that is — and it is the difference between a decision made and a
 * decision guessed at.
 */
export function PublishDialog({ moduleId, republish, onConfirm, onCancel }: Props) {
  const { t } = useTranslation();
  const [kind, setKind] = useState<RevisionKind | null>(null);
  const [impact, setImpact] = useState<RevisionImpact | null>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    // The heading rather than a button: nothing here should be one keystroke
    // away from being confirmed before it has been read.
    headingRef.current?.focus();
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const response = await fetch(`/api/content/modules/${moduleId}/revision-impact`);
        if (response.ok && !cancelled) setImpact(await response.json());
      } catch {
        // The count is context. Failing to fetch it leaves the warning below
        // unnumbered, and must never stop an author publishing.
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [moduleId]);

  const affected = impact === null ? 0 : impact.completed_learners + impact.in_progress_learners;

  return (
    <ModalDialog labelledBy="publish-dialog-heading" onCancel={onCancel}>
      <h3
        id="publish-dialog-heading"
        ref={headingRef}
        tabIndex={-1}
        className="text-lg font-semibold focus:outline-none"
      >
        {republish ? t("publish.dialog_heading_republish") : t("publish.dialog_heading")}
      </h3>
      <p className="text-sm text-fg-muted">{t("publish.dialog_body")}</p>

      <fieldset className="flex flex-col gap-3">
        <legend className="pb-2 text-sm font-medium">{t("publish.kind_legend")}</legend>
        {(["minor", "substantive"] as const).map((option) => (
          <label
            key={option}
            className="flex cursor-pointer gap-3 rounded-xl border border-border p-3 text-sm transition hover:border-primary"
          >
            <input
              type="radio"
              name="revision_kind"
              value={option}
              checked={kind === option}
              onChange={() => setKind(option)}
              className="mt-1"
            />
            <span className="flex flex-col gap-0.5">
              <span className="font-medium">{t(`publish.kind_${option}`)}</span>
              <span className="text-fg-muted">{t(`publish.kind_${option}_hint`)}</span>
            </span>
          </label>
        ))}
      </fieldset>

      {/* Only once `substantive` is actually chosen: a standing warning next to
          a question is noise, and noise next to a decision is how the decision
          stops being read. `role="status"` rather than an alert — it appears in
          answer to the author's own click, not out of nowhere. */}
      {kind === "substantive" && impact !== null && (
        <p
          role="status"
          className="rounded-xl border border-warning/40 bg-warning/10 px-4 py-3 text-sm text-warning"
        >
          {affected === 0
            ? t("publish.impact_none")
            : t("publish.impact_warning", {
                completed: impact.completed_learners,
                inProgress: impact.in_progress_learners,
                count: affected,
              })}
        </p>
      )}

      <div className="flex flex-wrap justify-end gap-2">
        <button
          type="button"
          onClick={onCancel}
          className="rounded-full border border-border bg-bg-elevated px-4 py-2 text-sm font-medium transition hover:-translate-y-0.5 hover:shadow-[var(--shadow)]"
        >
          {t("publish.dialog_cancel")}
        </button>
        <button
          type="button"
          disabled={kind === null}
          onClick={() => kind && onConfirm(kind)}
          className="rounded-full bg-[image:var(--gradient)] px-5 py-2 text-sm font-semibold text-primary-fg transition hover:-translate-y-0.5 hover:shadow-[var(--shadow)] disabled:opacity-60 disabled:hover:translate-y-0"
        >
          {t("publish.dialog_confirm")}
        </button>
      </div>
    </ModalDialog>
  );
}
