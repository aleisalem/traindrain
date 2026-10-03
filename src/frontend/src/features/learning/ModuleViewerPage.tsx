import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";

import { PagePreview } from "../content/PagePreview";
import type { LearnerModule, ProgressState } from "./types";

type ViewState =
  | { status: "loading" }
  | { status: "ready"; module: LearnerModule }
  /** The module was withdrawn, or was never open to this learner. Both look the
   *  same on purpose — the server does not say which, and neither does this. */
  | { status: "unavailable" }
  | { status: "error" };

const pillClassName =
  "rounded-full border border-border bg-bg-elevated px-4 py-2 text-sm font-medium transition hover:-translate-y-0.5 hover:shadow-[var(--shadow)] disabled:opacity-50 disabled:hover:translate-y-0";

/**
 * The module viewer: one page at a time, with a visible sense of how far
 * through you are, and an attestation at the end that only becomes available
 * once every page has actually been opened.
 *
 * Two accessibility properties are deliberate rather than incidental. Focus
 * moves to the new page's heading on every transition, so a keyboard or screen
 * reader user is *at* the new page rather than back where the Next button used
 * to be; and the page counter is announced through a live region, so progress
 * is not a purely visual fact. This is training content — content people cannot
 * reach is content that does not exist.
 */
export function ModuleViewerPage() {
  const { t } = useTranslation();
  const { groupId } = useParams();

  const [state, setState] = useState<ViewState>({ status: "loading" });
  const [index, setIndex] = useState(0);
  const [viewed, setViewed] = useState<string[]>([]);
  const [completedAt, setCompletedAt] = useState<string | null>(null);
  // A completion the material has outgrown: a substantive republish (ticket 7)
  // sets this, and the attestation becomes available again — the learner is
  // being asked to read a text they have not read, not to repeat themselves.
  const [superseded, setSuperseded] = useState(false);
  const [attesting, setAttesting] = useState(false);
  const [attestError, setAttestError] = useState<string | null>(null);
  const [switching, setSwitching] = useState(false);
  const [switchError, setSwitchError] = useState<string | null>(null);

  const headingRef = useRef<HTMLHeadingElement>(null);
  // Focus follows a *transition*, not the arrival: yanking focus out of the
  // document the moment a page loads would be its own kind of rude.
  const settled = useRef(false);

  // Shared by the initial load and an explicit language switch: both end with
  // the same question — which page is this learner on, in the text they are
  // now reading?
  const applyModule = useCallback((body: LearnerModule) => {
    setState({ status: "ready", module: body });
    // `progress` is null until they have read a page: opening a module
    // writes nothing, so a first visit simply has no record yet.
    setViewed(body.progress?.pages_viewed ?? []);
    setCompletedAt(body.progress?.completed_at ?? null);
    setSuperseded(body.progress?.superseded_at != null);
    // Resume: back at the page they left off on, not at the beginning of
    // material they have already read. A language switch resets
    // `current_page_id`, which lands this at the first page of the new text.
    const resumeAt = body.pages.findIndex((page) => page.id === body.progress?.current_page_id);
    setIndex(resumeAt >= 0 ? resumeAt : 0);
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const response = await fetch(`/api/me/modules/${groupId}`);
        if (response.status === 404) {
          if (!cancelled) setState({ status: "unavailable" });
          return;
        }
        if (!response.ok) {
          if (!cancelled) setState({ status: "error" });
          return;
        }
        const body: LearnerModule = await response.json();
        if (!cancelled) applyModule(body);
      } catch {
        if (!cancelled) setState({ status: "error" });
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [groupId, applyModule]);

  const switchLanguage = useCallback(
    async (language: string) => {
      setSwitching(true);
      setSwitchError(null);
      try {
        const response = await fetch(`/api/me/modules/${groupId}/language`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ language }),
        });
        if (!response.ok) {
          setSwitchError(t("learning.language_switch_error"));
          return;
        }
        const body: LearnerModule = await response.json();
        settled.current = false;
        applyModule(body);
      } catch {
        setSwitchError(t("learning.language_switch_error"));
      } finally {
        setSwitching(false);
      }
    },
    [groupId, applyModule, t],
  );

  const currentPage = state.status === "ready" ? state.module.pages[index] : undefined;
  const currentPageId = currentPage?.id;

  // Displaying a page is what marks it read — there is no "I have read this"
  // checkbox per page, because the attestation at the end is the assertion, and
  // asking twice would make neither of them mean anything.
  useEffect(() => {
    if (!currentPageId || !groupId) return;
    let cancelled = false;

    async function record() {
      try {
        const response = await fetch(
          `/api/me/modules/${groupId}/pages/${currentPageId}/view`,
          { method: "POST" },
        );
        if (!response.ok || cancelled) return;
        const progress: ProgressState = await response.json();
        setViewed(progress.pages_viewed);
      } catch {
        // A page that failed to register is a page the learner will be asked to
        // revisit before attesting, which is the safe direction to fail in.
      }
    }

    void record();
    return () => {
      cancelled = true;
    };
  }, [groupId, currentPageId]);

  useEffect(() => {
    if (settled.current) headingRef.current?.focus();
    else settled.current = state.status === "ready";
  }, [index, state.status]);

  const attest = useCallback(async () => {
    setAttesting(true);
    setAttestError(null);
    try {
      const response = await fetch(`/api/me/modules/${groupId}/complete`, { method: "POST" });
      if (!response.ok) {
        // The server sends the counts with its refusal so this can say how much
        // is left, rather than "no" and nothing else.
        let outstanding: number | undefined;
        try {
          outstanding = (await response.json())?.detail?.pages_outstanding;
        } catch {
          // A non-JSON body leaves the general message below.
        }
        setAttestError(
          response.status === 409
            ? t("learning.attest_error_outstanding", { count: outstanding ?? 0 })
            : t("learning.attest_error_unknown"),
        );
        return;
      }
      const progress: ProgressState = await response.json();
      setCompletedAt(progress.completed_at);
      setSuperseded(progress.superseded_at != null);
    } catch {
      setAttestError(t("learning.attest_error_unknown"));
    } finally {
      setAttesting(false);
    }
  }, [groupId, t]);

  if (state.status === "loading") return null;

  if (state.status === "unavailable" || state.status === "error") {
    return (
      <section className="flex max-w-2xl flex-col items-start gap-4">
        <h2 className="text-xl font-semibold">
          {state.status === "unavailable"
            ? t("learning.unavailable_heading")
            : t("learning.load_error")}
        </h2>
        {state.status === "unavailable" && (
          <p role="alert" className="text-sm text-fg-muted">
            {t("learning.unavailable_body")}
          </p>
        )}
        <Link
          to="/modules"
          className="rounded-full border border-border bg-bg-elevated px-4 py-2 text-sm font-medium transition hover:-translate-y-0.5 hover:shadow-[var(--shadow)]"
        >
          {t("learning.back_to_mine")}
        </Link>
      </section>
    );
  }

  const { module } = state;
  const total = module.pages.length;
  const viewedCount = viewed.length;
  const allViewed = total > 0 && module.pages.every((page) => viewed.includes(page.id));
  const onLastPage = index === total - 1;

  return (
    <article className="mx-auto flex w-full max-w-3xl flex-col gap-5">
      <header className="flex flex-col gap-3">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-xl font-semibold">{module.title}</h2>
          <p className="text-sm text-fg-muted">
            {t("learning.version_number", { version: module.version_number })}
          </p>
        </div>

        {/* Only shown when there is genuinely a choice — a single-language
            module has nothing to switch to. */}
        {module.available_languages.length > 1 && (
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <label htmlFor="learner-language" className="text-fg-muted">
              {t("learning.language_switch_label")}
            </label>
            <select
              id="learner-language"
              value={module.language}
              disabled={switching}
              onChange={(event) => void switchLanguage(event.target.value)}
              className="rounded-xl border border-border bg-bg-elevated px-3 py-1.5 transition-colors focus:border-primary focus:outline-none disabled:opacity-50"
            >
              {module.available_languages.map((language) => (
                <option key={language} value={language}>
                  {t(`learning.language_${language}`, { defaultValue: language })}
                </option>
              ))}
            </select>
            {switchError && (
              <p role="alert" className="text-danger">
                {switchError}
              </p>
            )}
          </div>
        )}

        <div className="flex flex-col gap-1">
          <div
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={total}
            aria-valuenow={viewedCount}
            aria-label={t("learning.progress_label")}
            className="h-2 w-full overflow-hidden rounded-full bg-bg-subtle"
          >
            <div
              className="h-full rounded-full bg-[image:var(--gradient)] transition-[width]"
              style={{ width: `${total === 0 ? 0 : (viewedCount / total) * 100}%` }}
            />
          </div>
          <p className="text-sm text-fg-muted">
            {t("learning.progress_pages", { viewed: viewedCount, total })}
          </p>
        </div>

        {/* The page change itself, said out loud. Visually it is obvious; to a
            screen reader it would otherwise be a silent content swap. */}
        <p role="status" aria-live="polite" className="sr-only">
          {t("learning.page_position", {
            position: index + 1,
            total,
            title: currentPage?.title ?? "",
          })}
        </p>
      </header>

      {completedAt !== null && (
        <p
          className={`rounded-2xl border border-border px-4 py-3 text-sm ${
            superseded ? "bg-warning/10 text-warning" : "bg-success/10 text-success"
          }`}
        >
          {superseded
            ? t("learning.superseded")
            : t("learning.completed_banner", {
                date: new Date(completedAt).toLocaleDateString(),
              })}
        </p>
      )}

      <section className="flex flex-col gap-4 rounded-2xl border border-border bg-bg-elevated p-5 shadow-[var(--shadow)] sm:p-7">
        <h3
          ref={headingRef}
          tabIndex={-1}
          className="text-lg font-medium outline-none focus-visible:ring-2 focus-visible:ring-primary"
        >
          {currentPage?.title}
        </h3>
        {currentPage && <PagePreview document={currentPage.body} />}
      </section>

      <nav className="flex flex-wrap items-center justify-between gap-3">
        <button
          type="button"
          disabled={index === 0}
          onClick={() => setIndex((current) => Math.max(0, current - 1))}
          className={pillClassName}
        >
          {t("learning.previous_page")}
        </button>
        <span className="text-sm text-fg-muted">
          {t("learning.page_of", { position: index + 1, total })}
        </span>
        <button
          type="button"
          disabled={onLastPage}
          onClick={() => setIndex((current) => Math.min(total - 1, current + 1))}
          className={pillClassName}
        >
          {t("learning.next_page")}
        </button>
      </nav>

      {module.attachments.length > 0 && (
        <section className="flex flex-col gap-2 rounded-2xl border border-border bg-bg-elevated p-5 shadow-[var(--shadow)]">
          <h3 className="text-sm font-medium">{t("learning.attachments_heading")}</h3>
          <ul className="flex flex-col gap-1 text-sm">
            {module.attachments.map((attachment) => (
              <li key={attachment.id}>
                {/* A plain link: the API authorizes the caller, redirects to
                    a short-lived signed URL, and the stored object carries its
                    own download disposition. */}
                <a href={attachment.url} className="text-primary underline underline-offset-2">
                  {attachment.original_filename}
                </a>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* The attestation lives on the last page and nowhere else: it is the end
          of the material, and offering it earlier would invite confirming
          something unread. Release 2's quiz gate goes immediately above it. */}
      {onLastPage && (
        <section className="flex flex-col gap-3 rounded-2xl border border-border bg-bg-elevated p-5 shadow-[var(--shadow)]">
          <h3 className="text-lg font-medium">{t("learning.attest_heading")}</h3>
          <p className="text-sm text-fg-muted">{t("learning.attest_body")}</p>
          {!allViewed && (
            <p className="text-sm text-fg-muted">
              {t("learning.attest_outstanding", { count: total - viewedCount })}
            </p>
          )}
          {attestError && (
            <p role="alert" className="text-sm text-danger">
              {attestError}
            </p>
          )}
          <button
            type="button"
            disabled={!allViewed || attesting || (completedAt !== null && !superseded)}
            onClick={() => void attest()}
            className="self-start rounded-full bg-[image:var(--gradient)] px-5 py-2.5 text-sm font-semibold text-primary-fg transition hover:-translate-y-0.5 hover:shadow-[var(--shadow)] disabled:opacity-50 disabled:hover:translate-y-0"
          >
            {completedAt !== null && !superseded
              ? t("learning.attest_done")
              : t("learning.attest_confirm")}
          </button>
        </section>
      )}
    </article>
  );
}
