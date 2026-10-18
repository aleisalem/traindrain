import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SCHEMA_VERSION } from "../../content/schema";
import i18n from "../../i18n";
import "../../i18n";
import { ModuleQuizPanel } from "./ModuleQuizPanel";
import type { QuizBody, QuizQuestion } from "./types";
import type { ModuleAssetsState } from "./useModuleAssets";

const MODULE_ID = "11111111-1111-1111-1111-111111111111";
const QUIZ_URL = `/api/content/modules/${MODULE_ID}/quiz`;

const NO_ASSETS: ModuleAssetsState = {
  images: [],
  attachments: [],
  totalBytes: 0,
  maxModuleBytes: 0,
  maxImageBytes: 0,
  maxAttachmentBytes: 0,
  loading: false,
  loadError: false,
  busy: false,
  error: null,
  upload: async () => null,
  remove: async () => undefined,
  clearError: () => undefined,
};

function doc(text: string) {
  return { type: "doc", content: [{ type: "paragraph", content: [{ type: "text", text }] }] };
}

function question(id: string, position: number, text: string): QuizQuestion {
  return {
    id,
    position,
    type: "single_choice",
    schema_version: SCHEMA_VERSION,
    prompt: doc(text),
    explanation: null,
    options: [
      { id: `${id}-a`, position: 0, text: "Right", is_correct: true },
      { id: `${id}-b`, position: 1, text: "Wrong", is_correct: false },
    ],
  };
}

function quiz(questions: QuizQuestion[], overrides: Partial<QuizBody> = {}): QuizBody {
  return {
    pass_mark_percent: 80,
    max_attempts: null,
    shuffle: false,
    reveal_after_pass: false,
    questions,
    problems: questions.length ? [] : [{ code: "no_questions", message: "x", question_id: null }],
    ...overrides,
  };
}

type Mocked = { status: number; body?: unknown };

function mockBackend(routes: Record<string, Mocked>) {
  const requests: { key: string; body: Record<string, unknown> | undefined }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const key = `${init?.method ?? "GET"} ${typeof input === "string" ? input : input.toString()}`;
      requests.push({ key, body: init?.body ? JSON.parse(init.body as string) : undefined });
      const hit = routes[key];
      if (!hit) throw new Error(`No mocked response for ${key}`);
      const hasBody = ![204, 205, 304].includes(hit.status);
      return new Response(hasBody ? JSON.stringify(hit.body) : null, {
        status: hit.status,
        headers: hasBody ? { "Content-Type": "application/json" } : {},
      });
    }),
  );
  return requests;
}

describe("ModuleQuizPanel", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("en");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("offers to add a quiz when the module has none, creating it with the defaults", async () => {
    const user = userEvent.setup();
    const requests = mockBackend({
      [`GET ${QUIZ_URL}`]: { status: 200, body: null },
      [`PUT ${QUIZ_URL}`]: { status: 200, body: quiz([]) },
    });
    render(<ModuleQuizPanel moduleId={MODULE_ID} assets={NO_ASSETS} />);

    await user.click(await screen.findByRole("button", { name: "Add a quiz" }));

    const put = requests.find((request) => request.key === `PUT ${QUIZ_URL}`);
    expect(put?.body).toEqual({
      pass_mark_percent: 80,
      max_attempts: null,
      shuffle: false,
      reveal_after_pass: false,
    });
    expect(await screen.findByLabelText("Pass mark (%)")).toHaveValue(80);
  });

  it("saves changed settings, including an attempt cap", async () => {
    const user = userEvent.setup();
    const requests = mockBackend({
      [`GET ${QUIZ_URL}`]: { status: 200, body: quiz([question("q1", 0, "Q one")]) },
      [`PUT ${QUIZ_URL}`]: {
        status: 200,
        body: quiz([question("q1", 0, "Q one")], { pass_mark_percent: 60, max_attempts: 2 }),
      },
    });
    render(<ModuleQuizPanel moduleId={MODULE_ID} assets={NO_ASSETS} />);

    const passMark = await screen.findByLabelText("Pass mark (%)");
    await user.clear(passMark);
    await user.type(passMark, "60");
    await user.click(screen.getByLabelText("Limit the number of attempts"));
    const cap = screen.getByLabelText("Maximum attempts");
    await user.clear(cap);
    await user.type(cap, "2");
    await user.click(screen.getByLabelText("Shuffle questions and answers"));
    await user.click(screen.getByRole("button", { name: "Save settings" }));

    const put = requests.find((request) => request.key === `PUT ${QUIZ_URL}`);
    expect(put?.body).toEqual({
      pass_mark_percent: 60,
      max_attempts: 2,
      shuffle: true,
      reveal_after_pass: false,
    });
    expect(await screen.findByText("Settings saved.")).toBeInTheDocument();
  });

  it("lists what blocks publishing, localized, with question numbers", async () => {
    mockBackend({
      [`GET ${QUIZ_URL}`]: {
        status: 200,
        body: quiz([question("q1", 0, "Q one")], {
          problems: [{ code: "duplicate_options", message: "x", question_id: "q1" }],
        }),
      },
    });
    render(<ModuleQuizPanel moduleId={MODULE_ID} assets={NO_ASSETS} />);

    expect(await screen.findByText("Question 1 has duplicate answer options.")).toBeInTheDocument();
  });

  it("adds a single-choice question with its options and correct answer", async () => {
    const user = userEvent.setup();
    const created = quiz([question("q1", 0, "What is phishing?")]);
    const requests = mockBackend({
      [`GET ${QUIZ_URL}`]: { status: 200, body: quiz([]) },
      [`POST ${QUIZ_URL}/questions`]: { status: 201, body: created },
    });
    render(<ModuleQuizPanel moduleId={MODULE_ID} assets={NO_ASSETS} />);

    await user.click(await screen.findByRole("button", { name: "Add Single choice" }));
    const form = screen.getByRole("form", { name: "Question editor" });
    await user.type(within(form).getByLabelText("Option 1"), "A scam");
    await user.type(within(form).getByLabelText("Option 2"), "A fish");
    await user.click(within(form).getByLabelText("Option 1 is correct"));
    await user.click(within(form).getByRole("button", { name: "Save question" }));

    const post = requests.find((request) => request.key === `POST ${QUIZ_URL}/questions`);
    expect(post?.body).toMatchObject({
      type: "single_choice",
      schema_version: SCHEMA_VERSION,
      options: [
        { text: "A scam", is_correct: true },
        { text: "A fish", is_correct: false },
      ],
    });
    expect(await screen.findByText("Question 1 · Single choice")).toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "Question editor" })).not.toBeInTheDocument();
  });

  it("allows several correct options only for multiple choice", async () => {
    const user = userEvent.setup();
    mockBackend({ [`GET ${QUIZ_URL}`]: { status: 200, body: quiz([]) } });
    render(<ModuleQuizPanel moduleId={MODULE_ID} assets={NO_ASSETS} />);

    await user.click(await screen.findByRole("button", { name: "Add Multiple choice" }));
    const form = screen.getByRole("form", { name: "Question editor" });
    await user.click(within(form).getByLabelText("Option 1 is correct"));
    await user.click(within(form).getByLabelText("Option 2 is correct"));
    expect(within(form).getByLabelText("Option 1 is correct")).toBeChecked();
    expect(within(form).getByLabelText("Option 2 is correct")).toBeChecked();
  });

  it("true/false questions fix the options and localize their labels", async () => {
    const user = userEvent.setup();
    const requests = mockBackend({
      [`GET ${QUIZ_URL}`]: { status: 200, body: quiz([]) },
      [`POST ${QUIZ_URL}/questions`]: { status: 201, body: quiz([question("q1", 0, "x")]) },
    });
    render(<ModuleQuizPanel moduleId={MODULE_ID} assets={NO_ASSETS} />);

    await user.click(await screen.findByRole("button", { name: "Add True / false" }));
    const form = screen.getByRole("form", { name: "Question editor" });
    expect(within(form).getByText("True")).toBeInTheDocument();
    expect(within(form).queryByLabelText("Option 1")).not.toBeInTheDocument();
    await user.click(within(form).getByLabelText("Option 2 is correct"));
    await user.click(within(form).getByRole("button", { name: "Save question" }));

    const post = requests.find((request) => request.key === `POST ${QUIZ_URL}/questions`);
    expect(post?.body?.options).toEqual([
      { text: "true", is_correct: false },
      { text: "false", is_correct: true },
    ]);
  });

  it("shows the server's refusal of a question instead of closing the form", async () => {
    const user = userEvent.setup();
    mockBackend({
      [`GET ${QUIZ_URL}`]: { status: 200, body: quiz([]) },
      [`POST ${QUIZ_URL}/questions`]: { status: 422, body: { detail: { code: "x" } } },
    });
    render(<ModuleQuizPanel moduleId={MODULE_ID} assets={NO_ASSETS} />);

    await user.click(await screen.findByRole("button", { name: "Add Single choice" }));
    await user.click(screen.getByRole("button", { name: "Save question" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/server rejected/);
    expect(screen.getByRole("form", { name: "Question editor" })).toBeInTheDocument();
  });

  it("reorders and deletes questions", async () => {
    const user = userEvent.setup();
    const two = quiz([question("q1", 0, "First"), question("q2", 1, "Second")]);
    const requests = mockBackend({
      [`GET ${QUIZ_URL}`]: { status: 200, body: two },
      [`POST ${QUIZ_URL}/questions/reorder`]: { status: 200, body: two },
      [`DELETE ${QUIZ_URL}/questions/q2`]: { status: 200, body: quiz([question("q1", 0, "First")]) },
    });
    render(<ModuleQuizPanel moduleId={MODULE_ID} assets={NO_ASSETS} />);

    await user.click(await screen.findByRole("button", { name: "Move question 2 up" }));
    expect(
      requests.find((request) => request.key === `POST ${QUIZ_URL}/questions/reorder`)?.body,
    ).toEqual({ question_ids: ["q2", "q1"] });

    await user.click(screen.getByRole("button", { name: "Delete question 2" }));
    await vi.waitFor(() => expect(screen.queryByText("Second")).not.toBeInTheDocument());
    expect(screen.queryByText("Second")).not.toBeInTheDocument();
  });

  it("removing the quiz asks first", async () => {
    const user = userEvent.setup();
    const requests = mockBackend({
      [`GET ${QUIZ_URL}`]: { status: 200, body: quiz([question("q1", 0, "First")]) },
      [`DELETE ${QUIZ_URL}`]: { status: 204 },
    });
    render(<ModuleQuizPanel moduleId={MODULE_ID} assets={NO_ASSETS} />);

    await user.click(await screen.findByRole("button", { name: "Remove quiz" }));
    expect(requests.some((request) => request.key === `DELETE ${QUIZ_URL}`)).toBe(false);
    await user.click(screen.getByRole("button", { name: "Yes, remove it" }));

    expect(await screen.findByText("This module has no quiz.")).toBeInTheDocument();
  });

  it("a try-out is graded by the server and shows the score in a live region", async () => {
    const user = userEvent.setup();
    const requests = mockBackend({
      [`GET ${QUIZ_URL}`]: { status: 200, body: quiz([question("q1", 0, "First")]) },
      [`POST ${QUIZ_URL}/tryout`]: {
        status: 200,
        body: {
          score_percent: 100,
          correct_count: 1,
          total: 1,
          pass_mark_percent: 80,
          passed: true,
          questions: [{ question_id: "q1", correct: true, correct_option_ids: ["q1-a"] }],
        },
      },
    });
    render(<ModuleQuizPanel moduleId={MODULE_ID} assets={NO_ASSETS} />);

    await user.click(await screen.findByRole("button", { name: "Try the quiz" }));
    const tryout = screen.getByRole("form", { name: "Quiz try-out" });
    await user.click(within(tryout).getByLabelText("Right"));
    await user.click(within(tryout).getByRole("button", { name: "Submit answers" }));

    expect(
      requests.find((request) => request.key === `POST ${QUIZ_URL}/tryout`)?.body,
    ).toEqual({ answers: { q1: ["q1-a"] } });
    const result = await within(tryout).findByText(/1 of 1 correct \(100%\)/);
    expect(result.closest("[aria-live]")).not.toBeNull();
    expect(within(tryout).getByText(/Passed/)).toBeInTheDocument();
  });

  it("renders in German", async () => {
    await i18n.changeLanguage("de");
    mockBackend({ [`GET ${QUIZ_URL}`]: { status: 200, body: null } });
    render(<ModuleQuizPanel moduleId={MODULE_ID} assets={NO_ASSETS} />);

    expect(await screen.findByRole("button", { name: "Quiz hinzufügen" })).toBeInTheDocument();
  });
});
