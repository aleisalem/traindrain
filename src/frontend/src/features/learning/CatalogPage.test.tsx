import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import i18n from "../../i18n";
import "../../i18n";
import { CatalogPage } from "./CatalogPage";
import { MyLearningPage } from "./MyLearningPage";
import type { CatalogEntry, LearnerModuleSummary } from "./types";

const ENTRY: CatalogEntry = {
  translation_group_id: "group-1",
  language: "en",
  title: "Phishing Awareness",
  description: "How to spot a phish.",
  estimated_duration_minutes: 15,
  page_count: 3,
  tags: [],
  started: false,
  completed_at: null,
  superseded_at: null,
};

function mockJson(url: string, body: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const requested = typeof input === "string" ? input : input.toString();
      return new Response(JSON.stringify(requested === url ? body : {}), {
        status: requested === url ? 200 : 404,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
}

/**
 * Filters a fixed catalog of entries the way the real
 * `GET /api/catalog/modules` route does, so a test can drive the filter UI
 * through several changes without pre-computing every intermediate query the
 * component happens to fire along the way (the free-text fields are
 * debounced, but `language` fires on every change).
 */
function mockCatalog(entries: CatalogEntry[]) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const requested = typeof input === "string" ? input : input.toString();
      const [, query] = requested.split("?");
      const search = new URLSearchParams(query ?? "");
      const q = search.get("q")?.toLowerCase();
      const language = search.get("language");
      const requestedTags = search.getAll("tags");
      const matched = entries.filter((entry) => {
        if (language && entry.language !== language) return false;
        if (
          q &&
          !entry.title.toLowerCase().includes(q) &&
          !entry.description?.toLowerCase().includes(q)
        ) {
          return false;
        }
        if (requestedTags.length > 0 && !requestedTags.every((tag) => entry.tags.includes(tag))) {
          return false;
        }
        return true;
      });
      return new Response(JSON.stringify(matched), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
}

function renderAt(path: string) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/modules" element={<MyLearningPage />} />
        <Route path="/modules/browse" element={<CatalogPage />} />
        <Route path="/modules/:groupId" element={<p>The viewer</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("the learner's lists", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("en");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("offers a catalog module to start, and links straight into it", async () => {
    mockJson("/api/catalog/modules", [ENTRY]);
    renderAt("/modules/browse");

    expect(await screen.findByText("Phishing Awareness")).toBeInTheDocument();
    expect(screen.getByText("3 pages")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Start" })).toHaveAttribute(
      "href",
      "/modules/group-1",
    );
  });

  it("says a started module is one to continue, and a finished one to reopen", async () => {
    mockJson("/api/catalog/modules", [
      { ...ENTRY, started: true },
      {
        ...ENTRY,
        translation_group_id: "group-2",
        title: "Passwords",
        completed_at: "2026-09-01T09:00:00Z",
      },
    ]);
    renderAt("/modules/browse");

    expect(await screen.findByRole("link", { name: "Continue" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open again" })).toBeInTheDocument();
  });

  it("does not call a superseded module completed", async () => {
    // The learner did complete it, and is being asked to read it again. A
    // green "Completed" badge here would contradict the module it links to.
    mockJson("/api/catalog/modules", [
      {
        ...ENTRY,
        started: true,
        completed_at: "2026-09-01T09:00:00Z",
        superseded_at: "2026-09-05T09:00:00Z",
      },
    ]);
    renderAt("/modules/browse");

    expect(await screen.findByText("Updated")).toBeInTheDocument();
    expect(screen.queryByText("Completed")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Read again" })).toBeInTheDocument();
  });

  it("keeps a completion on the learner's list after the module is withdrawn", async () => {
    const summary: LearnerModuleSummary = {
      translation_group_id: "group-1",
      title: "Phishing Awareness",
      language: "en",
      estimated_duration_minutes: 15,
      started_at: "2026-09-01T09:00:00Z",
      completed_at: "2026-09-02T09:00:00Z",
      completed_version_number: 2,
      superseded_at: null,
      available: false,
      due_date: null,
      requirement: null,
      overdue: false,
    };
    mockJson("/api/me/modules", [summary]);
    renderAt("/modules");

    // The record of what they did survives; the way back in does not.
    expect(await screen.findByText(/Completed/)).toBeInTheDocument();
    expect(screen.getByText("No longer available")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Open again" })).not.toBeInTheDocument();
  });

  it("shows an assigned module nobody has opened yet, with its due date", async () => {
    const summary: LearnerModuleSummary = {
      translation_group_id: "group-1",
      title: "Fire Safety",
      language: "en",
      estimated_duration_minutes: 10,
      started_at: null,
      completed_at: null,
      completed_version_number: null,
      superseded_at: null,
      available: true,
      due_date: "2026-12-01",
      requirement: "mandatory",
      overdue: false,
    };
    mockJson("/api/me/modules", [summary]);
    renderAt("/modules");

    expect(await screen.findByText("Not started")).toBeInTheDocument();
    expect(screen.getByText("Mandatory · Due 2026-12-01")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Start" })).toHaveAttribute(
      "href",
      "/modules/group-1",
    );
  });

  it("flags an assignment past its due date as overdue", async () => {
    const summary: LearnerModuleSummary = {
      translation_group_id: "group-1",
      title: "Fire Safety",
      language: "en",
      estimated_duration_minutes: 10,
      started_at: null,
      completed_at: null,
      completed_version_number: null,
      superseded_at: null,
      available: true,
      due_date: "2026-01-01",
      requirement: "mandatory",
      overdue: true,
    };
    mockJson("/api/me/modules", [summary]);
    renderAt("/modules");

    expect(await screen.findByText("Mandatory · Due 2026-01-01 · Overdue")).toBeInTheDocument();
  });

  it("never calls a completed assignment overdue", async () => {
    const summary: LearnerModuleSummary = {
      translation_group_id: "group-1",
      title: "Fire Safety",
      language: "en",
      estimated_duration_minutes: 10,
      started_at: "2026-01-01T09:00:00Z",
      completed_at: "2026-01-02T09:00:00Z",
      completed_version_number: 1,
      superseded_at: null,
      available: true,
      due_date: "2025-01-01",
      requirement: "mandatory",
      overdue: false,
    };
    mockJson("/api/me/modules", [summary]);
    renderAt("/modules");

    expect(await screen.findByText(/Completed/)).toBeInTheDocument();
    expect(screen.queryByText(/Overdue/)).not.toBeInTheDocument();
  });

  it("shows a catalog entry's tags", async () => {
    mockJson("/api/catalog/modules", [{ ...ENTRY, tags: ["phishing", "security"] }]);
    renderAt("/modules/browse");

    expect(await screen.findByText("phishing")).toBeInTheDocument();
    expect(screen.getByText("security")).toBeInTheDocument();
  });

  it("re-queries the catalog with a search term", async () => {
    mockCatalog([ENTRY, { ...ENTRY, translation_group_id: "group-2", title: "Fire Safety" }]);
    renderAt("/modules/browse");
    await screen.findByText("Phishing Awareness");
    expect(screen.getByText("Fire Safety")).toBeInTheDocument();

    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Search"), "fire");

    // "Fire Safety" is already on screen from the initial, unfiltered load —
    // the debounced re-query only proves itself once the non-matching entry
    // is gone.
    await waitFor(() => expect(screen.queryByText("Phishing Awareness")).not.toBeInTheDocument());
    expect(screen.getByText("Fire Safety")).toBeInTheDocument();
  });

  it("combines the language and tag filters into one query", async () => {
    mockCatalog([
      ENTRY,
      {
        ...ENTRY,
        translation_group_id: "group-3",
        title: "Sicherheitsschulung",
        language: "de",
        tags: ["security"],
      },
    ]);
    renderAt("/modules/browse");
    await screen.findByText("Phishing Awareness");

    const user = userEvent.setup();
    await user.selectOptions(screen.getByLabelText("Language"), "de");
    await user.type(screen.getByLabelText("Tags"), "security");

    expect(await screen.findByText("Sicherheitsschulung")).toBeInTheDocument();
    expect(screen.queryByText("Phishing Awareness")).not.toBeInTheDocument();
  });

  it("says nothing matches rather than the catalog being empty, when filters exclude everything", async () => {
    mockCatalog([ENTRY]);
    renderAt("/modules/browse");
    await screen.findByText("Phishing Awareness");

    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Search"), "nonexistent");

    expect(await screen.findByText("Nothing matches these filters.")).toBeInTheDocument();
  });
});
