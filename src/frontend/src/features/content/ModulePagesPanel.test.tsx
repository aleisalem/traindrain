import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SCHEMA_VERSION } from "../../content/schema";
import i18n from "../../i18n";
import "../../i18n";
import { ModulePagesPanel } from "./ModulePagesPanel";
import type { ModuleAssetsState } from "./useModuleAssets";

type MockResponse = { status: number; body?: unknown };

function createFetchMock() {
  const queues = new Map<string, MockResponse[]>();
  const requests: { key: string; body: Record<string, unknown> | undefined }[] = [];

  function queue(method: string, url: string, response: MockResponse) {
    const key = `${method} ${url}`;
    queues.set(key, [...(queues.get(key) ?? []), response]);
  }

  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    const method = init?.method ?? "GET";
    const key = `${method} ${url}`;
    requests.push({ key, body: init?.body ? JSON.parse(init.body as string) : undefined });
    const queued = queues.get(key)?.shift();
    if (!queued) throw new Error(`No mocked response queued for ${key}`);
    const hasBody = ![204, 205, 304].includes(queued.status);
    return new Response(hasBody ? JSON.stringify(queued.body) : null, {
      status: queued.status,
      headers: hasBody ? { "Content-Type": "application/json" } : {},
    });
  });

  return { fetchMock, queue, requests };
}

const MODULE_ID = "11111111-1111-1111-1111-111111111111";
const PAGES_URL = `/api/content/modules/${MODULE_ID}/pages`;

function page(id: string, title: string, position: number, text = title) {
  return {
    id,
    position,
    title,
    schema_version: SCHEMA_VERSION,
    body: {
      type: "doc",
      content: [{ type: "paragraph", content: [{ type: "text", text }] }],
    },
    updated_at: "2026-09-01T00:00:00Z",
  };
}

function pagesBody(draftRevision: number, pages: ReturnType<typeof page>[]) {
  return { draft_revision: draftRevision, schema_version: SCHEMA_VERSION, pages };
}

const TWO_PAGES = [page("page-a", "Intro", 0), page("page-b", "Details", 1)];

/**
 * A module with nothing uploaded. These tests are about pages, not assets —
 * the asset surface has its own file, which drives the real hook.
 */
const NO_ASSETS: ModuleAssetsState = {
  images: [],
  attachments: [],
  totalBytes: 0,
  maxModuleBytes: 100 * 1024 * 1024,
  maxImageBytes: 5 * 1024 * 1024,
  maxAttachmentBytes: 20 * 1024 * 1024,
  loading: false,
  loadError: false,
  busy: false,
  error: null,
  upload: async () => null,
  remove: async () => undefined,
  clearError: () => undefined,
};

describe("ModulePagesPanel", () => {
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

  it("saves an edited page with the draft token it loaded", async () => {
    const user = userEvent.setup();
    queue("GET", PAGES_URL, { status: 200, body: pagesBody(5, TWO_PAGES) });
    queue("PATCH", `${PAGES_URL}/page-a`, {
      status: 200,
      body: pagesBody(6, [page("page-a", "Introduction", 0), TWO_PAGES[1]]),
    });

    render(<ModulePagesPanel moduleId={MODULE_ID} assets={NO_ASSETS} />);

    const title = await screen.findByLabelText("Page title");
    await user.clear(title);
    await user.type(title, "Introduction");
    await user.click(screen.getByRole("button", { name: "Save page" }));

    const saved = requests.find((request) => request.key === `PATCH ${PAGES_URL}/page-a`);
    expect(saved?.body).toMatchObject({
      draft_revision: 5,
      title: "Introduction",
      schema_version: SCHEMA_VERSION,
    });
    expect(saved?.body?.body).toMatchObject({ type: "doc" });
    expect(await screen.findByRole("status")).toHaveTextContent("Saved.");
  });

  it("sends the following save with the token the server just returned", async () => {
    const user = userEvent.setup();
    queue("GET", PAGES_URL, { status: 200, body: pagesBody(5, TWO_PAGES) });
    queue("PATCH", `${PAGES_URL}/page-a`, { status: 200, body: pagesBody(6, TWO_PAGES) });
    queue("PATCH", `${PAGES_URL}/page-a`, { status: 200, body: pagesBody(7, TWO_PAGES) });

    render(<ModulePagesPanel moduleId={MODULE_ID} assets={NO_ASSETS} />);
    await screen.findByLabelText("Page title");

    await user.click(screen.getByRole("button", { name: "Save page" }));
    await screen.findByRole("status");
    await user.click(screen.getByRole("button", { name: "Save page" }));

    const saves = requests.filter((request) => request.key === `PATCH ${PAGES_URL}/page-a`);
    expect(saves.map((save) => save.body?.draft_revision)).toEqual([5, 6]);
  });

  it("tells the author to reload rather than losing a concurrent edit", async () => {
    const user = userEvent.setup();
    queue("GET", PAGES_URL, { status: 200, body: pagesBody(5, TWO_PAGES) });
    queue("PATCH", `${PAGES_URL}/page-a`, {
      status: 409,
      body: { detail: { code: "draft_conflict", message: "conflict", draft_revision: 9 } },
    });

    render(<ModulePagesPanel moduleId={MODULE_ID} assets={NO_ASSETS} />);
    await screen.findByLabelText("Page title");
    await user.click(screen.getByRole("button", { name: "Save page" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Someone else edited this module since you opened it.",
    );
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("reports a rejected document instead of pretending the page saved", async () => {
    const user = userEvent.setup();
    queue("GET", PAGES_URL, { status: 200, body: pagesBody(5, TWO_PAGES) });
    queue("PATCH", `${PAGES_URL}/page-a`, {
      status: 422,
      body: { detail: { code: "bad_href", message: "no" } },
    });

    render(<ModulePagesPanel moduleId={MODULE_ID} assets={NO_ASSETS} />);
    await screen.findByLabelText("Page title");
    await user.click(screen.getByRole("button", { name: "Save page" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("isn't allowed");
  });

  it("adds a page and selects it for writing", async () => {
    const user = userEvent.setup();
    queue("GET", PAGES_URL, { status: 200, body: pagesBody(5, TWO_PAGES) });
    queue("POST", PAGES_URL, {
      status: 201,
      body: pagesBody(6, [...TWO_PAGES, page("page-c", "Untitled page", 2, "")]),
    });

    render(<ModulePagesPanel moduleId={MODULE_ID} assets={NO_ASSETS} />);
    await screen.findByLabelText("Page title");
    await user.click(screen.getByRole("button", { name: "Add page" }));

    const created = requests.find((request) => request.key === `POST ${PAGES_URL}`);
    expect(created?.body).toMatchObject({ draft_revision: 5, schema_version: SCHEMA_VERSION });
    expect(await screen.findByLabelText("Page title")).toHaveValue("Untitled page");
  });

  it("reorders pages and shows the new order", async () => {
    const user = userEvent.setup();
    queue("GET", PAGES_URL, { status: 200, body: pagesBody(5, TWO_PAGES) });
    queue("POST", `${PAGES_URL}/reorder`, {
      status: 200,
      body: pagesBody(6, [page("page-b", "Details", 0), page("page-a", "Intro", 1)]),
    });

    render(<ModulePagesPanel moduleId={MODULE_ID} assets={NO_ASSETS} />);
    const nav = await screen.findByRole("navigation", { name: "Pages" });
    expect(within(nav).getAllByRole("listitem").map((item) => item.textContent)).toEqual([
      expect.stringContaining("1. Intro"),
      expect.stringContaining("2. Details"),
    ]);

    await user.click(screen.getByRole("button", { name: 'Move "Details" earlier' }));

    const reorder = requests.find((request) => request.key === `POST ${PAGES_URL}/reorder`);
    expect(reorder?.body).toEqual({ draft_revision: 5, page_ids: ["page-b", "page-a"] });
    expect(within(nav).getAllByRole("listitem").map((item) => item.textContent)).toEqual([
      expect.stringContaining("1. Details"),
      expect.stringContaining("2. Intro"),
    ]);
  });

  it("deletes a page", async () => {
    const user = userEvent.setup();
    queue("GET", PAGES_URL, { status: 200, body: pagesBody(5, TWO_PAGES) });
    queue("DELETE", `${PAGES_URL}/page-a`, {
      status: 200,
      body: pagesBody(6, [page("page-b", "Details", 0)]),
    });

    render(<ModulePagesPanel moduleId={MODULE_ID} assets={NO_ASSETS} />);
    await screen.findByLabelText("Page title");
    await user.click(screen.getByRole("button", { name: 'Delete "Intro"' }));

    const deleted = requests.find((request) => request.key === `DELETE ${PAGES_URL}/page-a`);
    expect(deleted?.body).toEqual({ draft_revision: 5 });
    const nav = await screen.findByRole("navigation", { name: "Pages" });
    expect(within(nav).getAllByRole("listitem")).toHaveLength(1);
  });

  it("previews every page in order, as a learner will read them", async () => {
    const user = userEvent.setup();
    queue("GET", PAGES_URL, { status: 200, body: pagesBody(5, TWO_PAGES) });

    render(<ModulePagesPanel moduleId={MODULE_ID} assets={NO_ASSETS} />);
    await screen.findByLabelText("Page title");
    await user.click(screen.getByRole("button", { name: "Preview" }));

    const articles = await screen.findAllByRole("article");
    expect(articles).toHaveLength(2);
    expect(articles[0]).toHaveTextContent("Page 1 of 2");
    expect(articles[0]).toHaveTextContent("Intro");
    expect(articles[1]).toHaveTextContent("Details");
    // The editor's toolbar is gone — this is the learner's view, not an
    // editable surface.
    expect(screen.queryByRole("toolbar")).not.toBeInTheDocument();
  });

  it("says plainly that saving a draft is not publishing it", async () => {
    queue("GET", PAGES_URL, { status: 200, body: pagesBody(5, TWO_PAGES) });

    render(<ModulePagesPanel moduleId={MODULE_ID} assets={NO_ASSETS} />);

    expect(
      await screen.findByText("Saved drafts are not visible to learners."),
    ).toBeInTheDocument();
  });
});
