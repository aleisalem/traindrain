import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import i18n from "../../i18n";
import "../../i18n";
import { ModuleFormPage } from "./ModuleFormPage";

type MockResponse = { status: number; body?: unknown };

/**
 * The presence heartbeat runs on a timer and on unmount, so it can't be
 * queued per-test without every test having to know about it. Tests that care
 * about presence queue their own response; everyone else gets an empty room.
 */
function presenceDefault(method: string, url: string): MockResponse | undefined {
  if (!url.endsWith("/editing")) return undefined;
  return method === "DELETE" ? { status: 204 } : { status: 200, body: { editors: [] } };
}

function createFetchMock() {
  const queues = new Map<string, MockResponse[]>();
  const requests: { key: string; body: unknown }[] = [];

  function queue(method: string, url: string, response: MockResponse) {
    const key = `${method} ${url}`;
    const existing = queues.get(key) ?? [];
    existing.push(response);
    queues.set(key, existing);
  }

  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    const method = init?.method ?? "GET";
    const key = `${method} ${url}`;
    requests.push({ key, body: init?.body ? JSON.parse(init.body as string) : undefined });
    const queued = queues.get(key)?.shift() ?? presenceDefault(method, url);
    if (!queued) throw new Error(`No mocked response queued for ${key}`);
    const hasBody = ![204, 205, 304].includes(queued.status);
    return new Response(hasBody ? JSON.stringify(queued.body) : null, {
      status: queued.status,
      headers: hasBody ? { "Content-Type": "application/json" } : {},
    });
  });

  return { fetchMock, queue, requests };
}

const MODULE = {
  id: "module-1",
  translation_group_id: "group-1",
  language: "de",
  title: "Phishing-Bewusstsein",
  description: "Wie man Phishing erkennt.",
  estimated_duration_minutes: 15,
  status: "draft",
  current_version_number: null,
  created_by: { id: "user-1", display_name: "Cora Manager" },
  last_edited_by: { id: "user-1", display_name: "Cora Manager" },
  created_at: "2026-09-01T00:00:00Z",
  updated_at: "2026-09-01T00:00:00Z",
};

/**
 * Opening a module for editing also mounts its pages panel, which loads the
 * draft. These tests are about the metadata form, so the pages come back
 * empty — `ModulePagesPanel.test.tsx` covers the authoring surface itself.
 */
function queueEmptyPages(
  queue: ReturnType<typeof createFetchMock>["queue"],
  moduleId = "module-1",
) {
  queue("GET", `/api/content/modules/${moduleId}/pages`, {
    status: 200,
    body: { draft_revision: 1, schema_version: 1, pages: [] },
  });
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/content/new" element={<ModuleFormPage />} />
        <Route path="/content/:moduleId" element={<ModuleFormPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("ModuleFormPage", () => {
  let queue: ReturnType<typeof createFetchMock>["queue"];
  let requests: ReturnType<typeof createFetchMock>["requests"];

  beforeEach(async () => {
    await i18n.changeLanguage("en");
    const mock = createFetchMock();
    queue = mock.queue;
    requests = mock.requests;
    vi.stubGlobal("fetch", mock.fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("creates a module with the metadata the author typed, then opens it for editing", async () => {
    const user = userEvent.setup();
    queue("POST", "/api/content/modules", { status: 201, body: MODULE });
    // A successful create navigates to the new module's own screen, which
    // loads it — so that fetch is part of the flow under test.
    queue("GET", "/api/content/modules/module-1", { status: 200, body: MODULE });
    queueEmptyPages(queue);

    renderAt("/content/new");

    await user.type(screen.getByLabelText("Title"), "Phishing Awareness");
    await user.type(screen.getByLabelText("Description"), "How to spot a phish.");
    await user.selectOptions(screen.getByLabelText("Language"), "de");
    await user.type(screen.getByLabelText("Estimated duration (minutes)"), "15");
    await user.click(screen.getByRole("button", { name: "Create module" }));

    const created = requests.find((request) => request.key === "POST /api/content/modules");
    expect(created?.body).toEqual({
      title: "Phishing Awareness",
      description: "How to spot a phish.",
      estimated_duration_minutes: 15,
      language: "de",
    });
    expect(await screen.findByRole("heading", { name: "Module details" })).toBeInTheDocument();
  });

  it("reports a validation failure rather than pretending the module saved", async () => {
    const user = userEvent.setup();
    queue("POST", "/api/content/modules", { status: 422 });

    renderAt("/content/new");

    await user.type(screen.getByLabelText("Title"), "Phishing Awareness");
    await user.click(screen.getByRole("button", { name: "Create module" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Please check the fields above and try again.",
    );
  });

  it("loads an existing module's metadata for editing and saves a partial change", async () => {
    const user = userEvent.setup();
    queue("GET", "/api/content/modules/module-1", { status: 200, body: MODULE });
    queueEmptyPages(queue);
    queue("PATCH", "/api/content/modules/module-1", {
      status: 200,
      body: { ...MODULE, title: "Phishing-Bewusstsein 2026" },
    });

    renderAt("/content/module-1");

    const title = await screen.findByLabelText("Title");
    expect(title).toHaveValue("Phishing-Bewusstsein");
    await user.clear(title);
    await user.type(title, "Phishing-Bewusstsein 2026");
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    const saved = requests.find((request) => request.key === "PATCH /api/content/modules/module-1");
    // No `language` — it is fixed at creation, so the edit form never sends it.
    expect(saved?.body).toEqual({
      title: "Phishing-Bewusstsein 2026",
      description: "Wie man Phishing erkennt.",
      estimated_duration_minutes: 15,
    });
    expect(await screen.findByRole("status")).toHaveTextContent("Saved.");
  });

  it("shows an existing module's language as fixed rather than editable", async () => {
    queue("GET", "/api/content/modules/module-1", { status: 200, body: MODULE });
    queueEmptyPages(queue);

    renderAt("/content/module-1");

    expect(
      await screen.findByText("Language: German (fixed once the module is created)"),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("Language")).not.toBeInTheDocument();
  });

  it("names who created the module and who edited it last", async () => {
    queue("GET", "/api/content/modules/module-1", { status: 200, body: MODULE });
    queueEmptyPages(queue);

    renderAt("/content/module-1");

    expect(await screen.findByText("Created by")).toBeInTheDocument();
    expect(screen.getAllByText("Cora Manager")).toHaveLength(2);
  });
});
