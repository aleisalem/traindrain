import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import i18n from "../../i18n";
import "../../i18n";
import { ModuleViewerPage } from "./ModuleViewerPage";
import type { LearnerModule, ProgressState } from "./types";

function paragraph(text: string) {
  return { type: "doc", content: [{ type: "paragraph", content: [{ type: "text", text }] }] };
}

const PAGES = [
  { id: "page-1", position: 0, title: "Spotting a phish", schema_version: 1, body: paragraph("Look at the sender.") },
  { id: "page-2", position: 1, title: "Reporting it", schema_version: 1, body: paragraph("Use the report button.") },
];

function moduleBody(overrides: Partial<ProgressState> = {}): LearnerModule {
  const progress: ProgressState = {
    pages_viewed: [],
    current_page_id: null,
    started_at: "2026-09-09T10:00:00Z",
    completed_at: null,
    completed_version_number: null,
    completed_module_id: null,
    superseded_at: null,
    ...overrides,
  };
  return {
    translation_group_id: "group-1",
    module_id: "module-1",
    language: "en",
    title: "Phishing Awareness",
    description: "How to spot a phish.",
    estimated_duration_minutes: 15,
    version_number: 2,
    pages: PAGES,
    attachments: [],
    available_languages: ["en"],
    progress,
  };
}

type MockResponse = { status: number; body?: unknown };

function mockBackend(responses: Record<string, MockResponse>) {
  const requested: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      const key = `${init?.method ?? "GET"} ${url}`;
      requested.push(key);
      const queued = responses[key] ?? { status: 404 };
      return new Response(JSON.stringify(queued.body ?? {}), {
        status: queued.status,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
  return requested;
}

/**
 * A server that remembers, because the behaviour under test is cumulative:
 * "every page has been seen" is a fact built up over several requests, and a
 * stateless stub could only ever assert one of them at a time.
 */
function viewerBackend(module: LearnerModule, { refuseComplete = false } = {}) {
  const requested: string[] = [];
  const viewed = new Set(module.progress?.pages_viewed ?? []);
  let current = module.progress?.current_page_id ?? null;
  let completedAt: string | null = module.progress?.completed_at ?? null;
  let supersededAt: string | null = module.progress?.superseded_at ?? null;

  const state = (): ProgressState => ({
    pages_viewed: [...viewed],
    current_page_id: current,
    started_at: module.progress?.started_at ?? "2026-09-09T10:00:00Z",
    completed_at: completedAt,
    completed_version_number: completedAt === null ? null : module.version_number,
    completed_module_id: completedAt === null ? null : module.module_id,
    superseded_at: supersededAt,
  });

  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      const key = `${init?.method ?? "GET"} ${url}`;
      requested.push(key);

      const json = (status: number, body: unknown) =>
        new Response(JSON.stringify(body), {
          status,
          headers: { "Content-Type": "application/json" },
        });

      if (key === "GET /api/me/modules/group-1") {
        // Null until they have read a page — opening a module writes nothing.
        return json(200, {
          ...module,
          progress: viewed.size === 0 && completedAt === null ? null : state(),
        });
      }
      const view = /^POST \/api\/me\/modules\/group-1\/pages\/(.+)\/view$/.exec(key);
      if (view) {
        viewed.add(view[1]);
        current = view[1];
        return json(200, state());
      }
      if (key === "POST /api/me/modules/group-1/complete") {
        // The same refusal the server makes, for the same reason: an
        // attestation about unread material is worth nothing.
        const outstanding = refuseComplete
          ? module.pages
          : module.pages.filter((page) => !viewed.has(page.id));
        if (outstanding.length > 0) {
          return json(409, {
            detail: {
              code: "pages_outstanding",
              pages_outstanding: outstanding.length,
              pages_total: module.pages.length,
            },
          });
        }
        completedAt = "2026-09-10T12:00:00Z";
        // A completion of the current text is current, exactly as the server
        // does it.
        supersededAt = null;
        return json(200, state());
      }
      return json(404, {});
    }),
  );
  return requested;
}

function renderViewer() {
  render(
    <MemoryRouter initialEntries={["/modules/group-1"]}>
      <Routes>
        <Route path="/modules/:groupId" element={<ModuleViewerPage />} />
        <Route path="/modules" element={<p>My learning</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("ModuleViewerPage", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("en");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("opens at the first page and moves forward and back through the module", async () => {
    const user = userEvent.setup();
    viewerBackend(moduleBody());
    renderViewer();

    expect(await screen.findByRole("heading", { name: "Spotting a phish" })).toBeInTheDocument();
    expect(screen.getByText("Look at the sender.")).toBeInTheDocument();
    // Nowhere to go back to from the first page.
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Next" }));

    expect(await screen.findByRole("heading", { name: "Reporting it" })).toBeInTheDocument();
    expect(screen.getByText("Use the report button.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Previous" }));

    expect(await screen.findByRole("heading", { name: "Spotting a phish" })).toBeInTheDocument();
  });

  it("moves focus to the new page's heading on a transition", async () => {
    const user = userEvent.setup();
    viewerBackend(moduleBody());
    renderViewer();
    await screen.findByRole("heading", { name: "Spotting a phish" });

    await user.click(screen.getByRole("button", { name: "Next" }));

    // A keyboard or screen-reader user is now *at* the new page, rather than
    // still parked on a button whose page has been swapped out underneath them.
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Reporting it" })).toHaveFocus(),
    );
  });

  it("records each page as it is displayed and shows how far through the learner is", async () => {
    const user = userEvent.setup();
    const requested = viewerBackend(moduleBody());
    renderViewer();

    await waitFor(() =>
      expect(requested).toContain("POST /api/me/modules/group-1/pages/page-1/view"),
    );
    expect(await screen.findByText("1 of 2 pages read")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Next" }));

    await waitFor(() =>
      expect(requested).toContain("POST /api/me/modules/group-1/pages/page-2/view"),
    );
    expect(await screen.findByText("2 of 2 pages read")).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "2");
  });

  it("resumes at the page the learner left off on", async () => {
    viewerBackend(
      moduleBody({ pages_viewed: ["page-1"], current_page_id: "page-2" }),
    );
    renderViewer();

    expect(await screen.findByRole("heading", { name: "Reporting it" })).toBeInTheDocument();
    expect(screen.getByText("Page 2 of 2")).toBeInTheDocument();
  });

  it("keeps the attestation out of reach until every page has been seen", async () => {
    const user = userEvent.setup();
    // On the last page with the first one never opened — the case the control
    // exists to refuse.
    viewerBackend(moduleBody({ pages_viewed: ["page-2"], current_page_id: "page-2" }));
    renderViewer();

    const confirm = await screen.findByRole("button", {
      name: "I have read and understood this",
    });
    await waitFor(() => expect(screen.getByText("1 of 2 pages read")).toBeInTheDocument());
    expect(confirm).toBeDisabled();
    expect(screen.getByText("1 page still to read.")).toBeInTheDocument();

    // Read the page they skipped, then come back.
    await user.click(screen.getByRole("button", { name: "Previous" }));
    await screen.findByRole("heading", { name: "Spotting a phish" });
    await user.click(screen.getByRole("button", { name: "Next" }));

    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "I have read and understood this" }),
      ).toBeEnabled(),
    );
  });

  it("confirms the module once every page has been read", async () => {
    const user = userEvent.setup();
    const requested = viewerBackend(
      moduleBody({ pages_viewed: ["page-1"], current_page_id: "page-2" }),
    );
    renderViewer();

    const confirm = await screen.findByRole("button", {
      name: "I have read and understood this",
    });
    await waitFor(() => expect(confirm).toBeEnabled());
    await user.click(confirm);

    await waitFor(() =>
      expect(requested).toContain("POST /api/me/modules/group-1/complete"),
    );
    expect(await screen.findByRole("button", { name: "Confirmed" })).toBeDisabled();
    expect(screen.getByText(/You confirmed this module on/)).toBeInTheDocument();
  });

  it("offers the attestation again when the material has changed since it was given", async () => {
    viewerBackend(
      moduleBody({
        pages_viewed: ["page-1", "page-2"],
        current_page_id: "page-2",
        completed_at: "2026-08-01T09:00:00Z",
        completed_version_number: 1,
        // What a substantive republish leaves behind: the completion stands as
        // a record, but it is no longer a completion of *this* text.
        superseded_at: "2026-09-01T09:00:00Z",
      }),
    );
    renderViewer();

    expect(
      await screen.findByText(/This module has changed since you completed it/),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "I have read and understood this" }),
      ).toBeEnabled(),
    );
  });

  it("says how many pages are left when the server refuses the attestation", async () => {
    const user = userEvent.setup();
    viewerBackend(moduleBody({ pages_viewed: ["page-1"], current_page_id: "page-2" }), {
      refuseComplete: true,
    });
    renderViewer();

    const confirm = await screen.findByRole("button", {
      name: "I have read and understood this",
    });
    await waitFor(() => expect(confirm).toBeEnabled());
    await user.click(confirm);

    // The counts come back with the 409 precisely so the learner is told how
    // much is left rather than just "no".
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Read the 2 pages you haven't opened yet before confirming.",
    );
  });

  it("says so plainly when the module has been withdrawn", async () => {
    mockBackend({
      "GET /api/me/modules/group-1": {
        status: 404,
        body: { detail: { code: "module_unavailable" } },
      },
    });
    renderViewer();

    expect(
      await screen.findByRole("heading", { name: "This module is no longer available" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Anything you already completed is still recorded.",
    );
  });

  // --- Switching language --------------------------------------------------

  const EN_VARIANT: LearnerModule = {
    translation_group_id: "group-1",
    module_id: "module-en",
    language: "en",
    title: "Phishing Awareness",
    description: "How to spot a phish.",
    estimated_duration_minutes: 15,
    version_number: 1,
    pages: [
      {
        id: "en-page-1",
        position: 0,
        title: "Spotting a phish",
        schema_version: 1,
        body: paragraph("Look at the sender."),
      },
    ],
    attachments: [],
    available_languages: ["en", "de"],
    progress: {
      pages_viewed: [],
      current_page_id: null,
      started_at: "2026-09-09T10:00:00Z",
      completed_at: null,
      completed_version_number: null,
      completed_module_id: null,
      superseded_at: null,
    },
  };

  const DE_VARIANT: LearnerModule = {
    ...EN_VARIANT,
    module_id: "module-de",
    language: "de",
    title: "Phishing-Bewusstsein",
    pages: [
      {
        id: "de-page-1",
        position: 0,
        title: "Eine Phishing-Mail erkennen",
        schema_version: 1,
        body: paragraph("Achten Sie auf den Absender."),
      },
    ],
  };

  it("only offers a language switch when there is more than one to read", async () => {
    viewerBackend(moduleBody());
    renderViewer();

    await screen.findByRole("heading", { name: "Spotting a phish" });

    expect(screen.queryByLabelText("Read in")).not.toBeInTheDocument();
  });

  it("lets a learner switch to another available language", async () => {
    const user = userEvent.setup();
    mockBackend({
      "GET /api/me/modules/group-1": { status: 200, body: EN_VARIANT },
      "POST /api/me/modules/group-1/pages/en-page-1/view": {
        status: 200,
        body: { ...EN_VARIANT.progress, pages_viewed: ["en-page-1"], current_page_id: "en-page-1" },
      },
      "POST /api/me/modules/group-1/language": { status: 200, body: DE_VARIANT },
      "POST /api/me/modules/group-1/pages/de-page-1/view": {
        status: 200,
        body: { ...DE_VARIANT.progress, pages_viewed: ["de-page-1"], current_page_id: "de-page-1" },
      },
    });
    renderViewer();
    await screen.findByRole("heading", { name: "Spotting a phish" });

    await user.selectOptions(screen.getByLabelText("Read in"), "de");

    expect(
      await screen.findByRole("heading", { name: "Eine Phishing-Mail erkennen" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Read in")).toHaveValue("de");
  });

  it("shows an error and keeps the current text if the switch fails", async () => {
    const user = userEvent.setup();
    mockBackend({
      "GET /api/me/modules/group-1": { status: 200, body: EN_VARIANT },
      "POST /api/me/modules/group-1/pages/en-page-1/view": {
        status: 200,
        body: { ...EN_VARIANT.progress, pages_viewed: ["en-page-1"], current_page_id: "en-page-1" },
      },
      "POST /api/me/modules/group-1/language": {
        status: 404,
        body: { detail: { code: "variant_unavailable" } },
      },
    });
    renderViewer();
    await screen.findByRole("heading", { name: "Spotting a phish" });

    await user.selectOptions(screen.getByLabelText("Read in"), "de");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Couldn't switch language. Please try again.",
    );
    expect(screen.getByRole("heading", { name: "Spotting a phish" })).toBeInTheDocument();
  });
});
