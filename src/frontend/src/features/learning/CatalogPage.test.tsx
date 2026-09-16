import { render, screen } from "@testing-library/react";
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
});
