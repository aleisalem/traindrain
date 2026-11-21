import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import "../../i18n";
import { ModuleViewerPage } from "./ModuleViewerPage";
import { QuizPanel } from "./QuizPanel";
import type { Attempt, LearnerModule, QuizState, QuizSummary } from "./types";

function doc(text: string) {
  return { type: "doc", content: [{ type: "paragraph", content: [{ type: "text", text }] }] };
}

const SUMMARY: QuizSummary = {
  question_count: 2,
  pass_mark_percent: 80,
  max_attempts: 2,
  attempts_used: 0,
  attempts_remaining: 2,
  exhausted: false,
  passed: false,
  best_score_percent: null,
};

const QUESTIONS: Attempt["questions"] = [
  {
    id: "q1",
    type: "single_choice",
    schema_version: 1,
    prompt: doc("Which is a phish?"),
    options: [
      { id: "q1a", text: "A scam email" },
      { id: "q1b", text: "A fish" },
    ],
  },
  {
    id: "q2",
    type: "true_false",
    schema_version: 1,
    prompt: doc("Links can be malicious."),
    options: [
      { id: "q2t", text: "true" },
      { id: "q2f", text: "false" },
    ],
  },
];

/** A server that grades: the right answers are q1a and q2t. */
function quizBackend({ passAll = false, maxAttempts = 2 } = {}) {
  const calls: string[] = [];
  let attempt: Attempt | null = null;
  let used = 0;
  let passed = false;
  const summary = (): QuizSummary => ({
    ...SUMMARY,
    max_attempts: maxAttempts,
    attempts_used: used,
    attempts_remaining: maxAttempts - used,
    exhausted: used >= maxAttempts && !passed,
    passed,
    best_score_percent: attempt?.result?.score_percent ?? null,
  });
  const state = (): QuizState => ({ summary: summary(), attempt });

  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      const method = init?.method ?? "GET";
      calls.push(`${method} ${url}`);
      const json = (body: unknown, status = 200) =>
        new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
      const base = "/api/me/modules/group-1/quiz";

      if (method === "GET" && url === base) return json(state());
      if (method === "POST" && (url === `${base}/attempts` || url === `${base}/retake`)) {
        if (!attempt || attempt.submitted_at) {
          used += 1;
          attempt = {
            id: `attempt-${used}`,
            version_number: 1,
            started_at: "2026-10-18T10:00:00Z",
            submitted_at: null,
            questions: QUESTIONS,
            answers: {},
            result: null,
          };
        }
        return json(state());
      }
      const put = /\/answers\/(q\d)$/.exec(url);
      if (method === "PUT" && put && attempt) {
        attempt = { ...attempt, answers: { ...attempt.answers, [put[1]]: JSON.parse(String(init?.body)).option_ids } };
        return json(state());
      }
      if (method === "POST" && url.endsWith("/submit") && attempt) {
        const right = (attempt.answers.q1 ?? []).join() === "q1a" && (attempt.answers.q2 ?? []).join() === "q2t";
        const ok = passAll || right;
        const score = ok ? 100 : 0;
        passed = passed || ok;
        attempt = {
          ...attempt,
          submitted_at: "2026-10-18T10:05:00Z",
          result: {
            score_percent: score,
            correct_count: ok ? 2 : 0,
            total: 2,
            pass_mark_percent: 80,
            passed: ok,
            questions: [
              { question_id: "q1", correct: ok },
              { question_id: "q2", correct: ok },
            ],
            revealed: null,
          },
        };
        return json(state());
      }
      return json({}, 404);
    }),
  );
  return calls;
}

afterEach(() => vi.unstubAllGlobals());

function renderPanel(props: Partial<React.ComponentProps<typeof QuizPanel>> = {}) {
  const onSummary = vi.fn();
  const onReread = vi.fn();
  render(
    <QuizPanel
      groupId="group-1"
      summary={SUMMARY}
      pagesDone
      onSummary={onSummary}
      onReread={onReread}
      {...props}
    />,
  );
  return { onSummary, onReread };
}

describe("QuizPanel", () => {
  it("stays locked until every page is read", () => {
    const calls = quizBackend();
    renderPanel({ pagesDone: false });
    expect(screen.getByText(/read every page to unlock the quiz/i)).toBeInTheDocument();
    expect(calls).toHaveLength(0);
  });

  it("is operable entirely by keyboard and announces the outcome", async () => {
    quizBackend();
    const user = userEvent.setup();
    renderPanel();

    const start = await screen.findByRole("button", { name: /start the quiz/i });
    expect(screen.getByText(/2 attempts left/i)).toBeInTheDocument();
    start.focus();
    await user.keyboard("{Enter}");

    // Question 1: focus lands on its heading; pick the answer with the keyboard.
    const heading = await screen.findByRole("heading", { name: /question 1 of 2/i });
    await waitFor(() => expect(screen.getByRole("radio", { name: "A scam email" })).toBeInTheDocument());
    await user.tab(); // heading is focusable (tabIndex -1) via script; first radio next
    screen.getByRole("radio", { name: "A scam email" }).focus();
    await user.keyboard(" ");
    await waitFor(() => expect(screen.getByRole("radio", { name: "A scam email" })).toBeChecked());
    expect(heading).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /^next$/i }));
    await waitFor(() => expect(document.activeElement?.textContent).toMatch(/question 2 of 2/i));
    expect(screen.getByRole("status")).toHaveTextContent(/question 2 of 2/i);
    await user.click(screen.getByRole("radio", { name: "True" }));
    await user.click(screen.getByRole("button", { name: /submit answers/i }));

    const result = await screen.findByRole("heading", { name: /passed!/i });
    await waitFor(() => expect(result).toHaveFocus());
    expect(screen.getByRole("status")).toHaveTextContent(/you passed with 100%/i);
    expect(screen.getByText(/you can now confirm the module/i)).toBeInTheDocument();
  });

  it("flags wrong questions after a failure and offers both retakes", async () => {
    quizBackend();
    const user = userEvent.setup();
    const { onReread, onSummary } = renderPanel();

    await user.click(await screen.findByRole("button", { name: /start the quiz/i }));
    await user.click(await screen.findByRole("radio", { name: "A fish" }));
    await user.click(screen.getByRole("button", { name: /^next$/i }));
    await user.click(screen.getByRole("radio", { name: "True" }));
    await user.click(screen.getByRole("button", { name: /submit answers/i }));

    expect(await screen.findByRole("heading", { name: /not passed this time/i })).toBeInTheDocument();
    expect(screen.getAllByText(/not correct/i)).toHaveLength(2);
    // No answer key anywhere on a failed attempt.
    expect(screen.queryByText(/correct answer/i)).not.toBeInTheDocument();
    expect(screen.getByText(/1 attempt left/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /re-read the module first/i }));
    await waitFor(() => expect(onReread).toHaveBeenCalled());
    expect(onSummary).toHaveBeenCalled();
  });

  it("retaking the quiz only starts a fresh attempt", async () => {
    const calls = quizBackend();
    const user = userEvent.setup();
    const { onReread } = renderPanel();
    await user.click(await screen.findByRole("button", { name: /start the quiz/i }));
    await user.click(await screen.findByRole("radio", { name: "A fish" }));
    await user.click(screen.getByRole("button", { name: /^next$/i }));
    await user.click(screen.getByRole("button", { name: /submit answers/i }));
    await screen.findByRole("heading", { name: /not passed this time/i });

    await user.click(screen.getByRole("button", { name: /retake the quiz only/i }));
    expect(await screen.findByRole("heading", { name: /question 1 of 2/i })).toBeInTheDocument();
    expect(calls).toContain("POST /api/me/modules/group-1/quiz/retake");
    expect(onReread).not.toHaveBeenCalled();
  });

  it("says when attempts are used up and points to an Administrator", async () => {
    quizBackend({ maxAttempts: 1 });
    const user = userEvent.setup();
    renderPanel();
    await user.click(await screen.findByRole("button", { name: /start the quiz/i }));
    await user.click(await screen.findByRole("radio", { name: "A fish" }));
    await user.click(screen.getByRole("button", { name: /^next$/i }));
    await user.click(screen.getByRole("button", { name: /submit answers/i }));

    expect(await screen.findByText(/ask an administrator to reset/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /retake/i })).not.toBeInTheDocument();
  });
});

describe("the viewer's attestation", () => {
  function moduleWithQuiz(): LearnerModule {
    return {
      translation_group_id: "group-1",
      module_id: "module-1",
      language: "en",
      title: "Phishing",
      description: null,
      estimated_duration_minutes: null,
      version_number: 1,
      pages: [{ id: "page-1", position: 0, title: "Only page", schema_version: 1, body: doc("Hi") }],
      attachments: [],
      available_languages: ["en"],
      progress: null,
      quiz: SUMMARY,
    } as unknown as LearnerModule;
  }

  it("stays locked until the quiz is passed", async () => {
    const quiz = quizBackend({ passAll: true });
    const inner = globalThis.fetch;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = typeof input === "string" ? input : input.toString();
        if (url === "/api/me/modules/group-1") {
          return new Response(JSON.stringify(moduleWithQuiz()), { status: 200 });
        }
        if (url.endsWith("/view")) {
          return new Response(
            JSON.stringify({ pages_viewed: ["page-1"], current_page_id: "page-1", started_at: "x", completed_at: null }),
            { status: 200 },
          );
        }
        return inner(input, init);
      }),
    );
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/modules/group-1"]}>
        <Routes>
          <Route path="/modules/:groupId" element={<ModuleViewerPage />} />
        </Routes>
      </MemoryRouter>,
    );

    const attest = await screen.findByRole("button", { name: /i have read and understood this/i });
    expect(attest).toBeDisabled();
    await user.click(await screen.findByRole("button", { name: /start the quiz/i }));
    await user.click(await screen.findByRole("radio", { name: "A scam email" }));
    await user.click(within(screen.getByRole("region", { name: /^quiz$/i })).getByRole("button", { name: /^next$/i }));
    await user.click(screen.getByRole("radio", { name: "True" }));
    await user.click(screen.getByRole("button", { name: /submit answers/i }));
    await screen.findByRole("heading", { name: /passed!/i });
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /i have read and understood this/i })).toBeEnabled(),
    );
    expect(quiz.length).toBeGreaterThan(0);
  });
});
