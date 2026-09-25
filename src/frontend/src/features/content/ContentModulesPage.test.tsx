import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import i18n from "../../i18n";
import "../../i18n";
import { ContentModulesPage } from "./ContentModulesPage";
import type { ModuleBody } from "./types";

const ACTOR = { id: "user-1", display_name: "Cora Manager" };

function makeModule(overrides: Partial<ModuleBody>): ModuleBody {
  return {
    id: "module-1",
    translation_group_id: "group-1",
    language: "en",
    title: "Phishing Awareness",
    description: "How to spot a phish.",
    estimated_duration_minutes: 15,
    status: "draft",
    catalog_visible: false,
    current_version_number: null,
    tags: [],
    created_by: ACTOR,
    last_edited_by: ACTOR,
    created_at: "2026-09-01T00:00:00Z",
    updated_at: "2026-09-01T00:00:00Z",
    ...overrides,
  };
}

const PHISHING = makeModule({ tags: ["phishing", "security"] });
const FIRE_SAFETY = makeModule({
  id: "module-2",
  title: "Fire Safety",
  description: "What to do in a fire.",
  tags: ["safety"],
});
const SICHERHEITSSCHULUNG = makeModule({
  id: "module-3",
  title: "Sicherheitsschulung",
  language: "de",
  status: "published",
  tags: ["security"],
});

/**
 * Filters a fixed catalog of modules the way the real
 * `GET /api/content/modules` route does — so a test can drive the UI through
 * several filter changes without pre-computing every intermediate query the
 * component happens to fire along the way.
 */
function filterModules(modules: ModuleBody[], search: URLSearchParams): ModuleBody[] {
  const q = search.get("q")?.toLowerCase();
  const language = search.get("language");
  const status = search.get("status");
  const requestedTags = search.getAll("tags");
  return modules.filter((module) => {
    if (language && module.language !== language) return false;
    if (status && module.status !== status) return false;
    if (q && !module.title.toLowerCase().includes(q) && !module.description?.toLowerCase().includes(q)) {
      return false;
    }
    if (requestedTags.length > 0 && !requestedTags.every((tag) => module.tags.includes(tag))) {
      return false;
    }
    return true;
  });
}

function mockBackend(modules: ModuleBody[], tags: string[]) {
  const requestedUrls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      requestedUrls.push(url);
      const [path, query] = url.split("?");
      if (path === "/api/content/tags") {
        return new Response(JSON.stringify(tags), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      const matched = filterModules(modules, new URLSearchParams(query ?? ""));
      return new Response(JSON.stringify(matched), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
  return requestedUrls;
}

function renderPage() {
  render(
    <MemoryRouter initialEntries={["/content"]}>
      <Routes>
        <Route path="/content" element={<ContentModulesPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("ContentModulesPage", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("en");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("lists a module's tags alongside its metadata", async () => {
    mockBackend([PHISHING], ["phishing", "security"]);
    renderPage();

    const card = (await screen.findByText("Phishing Awareness")).closest("li");
    expect(card).not.toBeNull();
    expect(within(card as HTMLElement).getByText("phishing")).toBeInTheDocument();
    expect(within(card as HTMLElement).getByText("security")).toBeInTheDocument();
  });

  it("re-queries the module list with a search term", async () => {
    const requestedUrls = mockBackend([PHISHING, FIRE_SAFETY], []);
    renderPage();
    await screen.findByText("Phishing Awareness");
    expect(screen.getByText("Fire Safety")).toBeInTheDocument();

    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Search"), "fire");

    // "Fire Safety" is already on screen from the initial, unfiltered load —
    // the debounced re-query only proves itself once the non-matching module
    // is gone.
    await waitFor(() => expect(screen.queryByText("Phishing Awareness")).not.toBeInTheDocument());
    expect(screen.getByText("Fire Safety")).toBeInTheDocument();
    expect(requestedUrls).toContain("/api/content/modules?q=fire");
  });

  it("combines the language, status, and tag filters into one query", async () => {
    const requestedUrls = mockBackend(
      [PHISHING, FIRE_SAFETY, SICHERHEITSSCHULUNG],
      ["phishing", "safety", "security"],
    );
    renderPage();
    await screen.findByText("Phishing Awareness");

    const user = userEvent.setup();
    await user.selectOptions(screen.getByLabelText("Language"), "de");
    await user.selectOptions(screen.getByLabelText("Status"), "published");
    await user.selectOptions(await screen.findByLabelText("Tag"), "security");

    expect(await screen.findByText("Sicherheitsschulung")).toBeInTheDocument();
    expect(screen.queryByText("Phishing Awareness")).not.toBeInTheDocument();
    expect(screen.queryByText("Fire Safety")).not.toBeInTheDocument();
    expect(requestedUrls).toContain(
      "/api/content/modules?language=de&status=published&tags=security",
    );
  });
});
