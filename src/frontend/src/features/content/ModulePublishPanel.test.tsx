import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import i18n from "../../i18n";
import "../../i18n";
import { ModulePublishPanel } from "./ModulePublishPanel";
import type { ModuleBody, ModuleVersion } from "./types";

const MODULE: ModuleBody = {
  id: "module-1",
  translation_group_id: "group-1",
  language: "en",
  title: "Phishing Awareness",
  description: "How to spot a phish.",
  estimated_duration_minutes: 15,
  status: "draft",
  catalog_visible: false,
  current_version_number: null,
  created_by: { id: "user-1", display_name: "Cora Manager" },
  last_edited_by: { id: "user-1", display_name: "Cora Manager" },
  created_at: "2026-09-01T00:00:00Z",
  updated_at: "2026-09-01T00:00:00Z",
};

const PUBLISHED: ModuleBody = { ...MODULE, status: "published", current_version_number: 1 };

const VERSION: ModuleVersion = {
  id: "version-1",
  version_number: 1,
  revision_kind: "minor",
  published_at: "2026-09-02T09:00:00Z",
  published_by: { id: "user-1", display_name: "Cora Manager" },
  title: "Phishing Awareness",
  page_count: 3,
};

type MockResponse = { status: number; body?: unknown };
type Requested = { key: string; body: unknown };

function mockBackend(responses: Record<string, MockResponse>) {
  const requested: Requested[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      const key = `${init?.method ?? "GET"} ${url}`;
      requested.push({ key, body: init?.body ? JSON.parse(init.body as string) : undefined });
      const queued = responses[key] ?? { status: 404 };
      return new Response(JSON.stringify(queued.body ?? {}), {
        status: queued.status,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
  return requested;
}

function renderPanel(module: ModuleBody, onChanged = vi.fn()) {
  render(
    <MemoryRouter initialEntries={["/content/module-1"]}>
      <Routes>
        <Route
          path="/content/:moduleId"
          element={<ModulePublishPanel module={module} onChanged={onChanged} />}
        />
        <Route path="/content/module-2" element={<p>The copy</p>} />
      </Routes>
    </MemoryRouter>,
  );
  return onChanged;
}

describe("ModulePublishPanel", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("en");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("will not publish until the author has said whether the revision is minor or substantive", async () => {
    const user = userEvent.setup();
    const requested = mockBackend({
      "GET /api/content/modules/module-1/versions": { status: 200, body: [] },
      "POST /api/content/modules/module-1/publish": { status: 200, body: PUBLISHED },
    });
    const onChanged = renderPanel(MODULE);

    await user.click(screen.getByRole("button", { name: "Publish" }));

    const dialog = await screen.findByRole("dialog");
    const confirm = within(dialog).getByRole("button", { name: "Publish" });
    // The question has no default answer, so there is nothing to confirm yet.
    expect(confirm).toBeDisabled();
    expect(screen.getByRole("radio", { name: /Minor/ })).not.toBeChecked();
    expect(screen.getByRole("radio", { name: /Substantive/ })).not.toBeChecked();
    expect(
      requested.some((request) => request.key.endsWith("/publish")),
    ).toBe(false);

    await user.click(screen.getByRole("radio", { name: /Substantive/ }));
    expect(confirm).toBeEnabled();
    await user.click(confirm);

    await waitFor(() =>
      expect(
        requested.find((request) => request.key === "POST /api/content/modules/module-1/publish")
          ?.body,
      ).toEqual({ revision_kind: "substantive" }),
    );
    expect(onChanged).toHaveBeenCalledWith(PUBLISHED);
  });

  it("publishes a minor revision when that is the choice", async () => {
    const user = userEvent.setup();
    const requested = mockBackend({
      "GET /api/content/modules/module-1/versions": { status: 200, body: [] },
      "POST /api/content/modules/module-1/publish": { status: 200, body: PUBLISHED },
    });
    renderPanel(MODULE);

    await user.click(screen.getByRole("button", { name: "Publish" }));
    await user.click(await screen.findByRole("radio", { name: /Minor/ }));
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Publish" }));

    await waitFor(() =>
      expect(
        requested.find((request) => request.key === "POST /api/content/modules/module-1/publish")
          ?.body,
      ).toEqual({ revision_kind: "minor" }),
    );
  });

  it("cancelling the dialog publishes nothing", async () => {
    const user = userEvent.setup();
    const requested = mockBackend({
      "GET /api/content/modules/module-1/versions": { status: 200, body: [] },
    });
    renderPanel(MODULE);

    await user.click(screen.getByRole("button", { name: "Publish" }));
    await user.click(await screen.findByRole("button", { name: "Cancel" }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(requested.some((request) => request.key.endsWith("/publish"))).toBe(false);
  });

  it("says a module with no pages cannot be published rather than failing silently", async () => {
    const user = userEvent.setup();
    mockBackend({
      "GET /api/content/modules/module-1/versions": { status: 200, body: [] },
      "POST /api/content/modules/module-1/publish": {
        status: 409,
        body: { detail: { code: "empty_module" } },
      },
    });
    renderPanel(MODULE);

    await user.click(screen.getByRole("button", { name: "Publish" }));
    await user.click(await screen.findByRole("radio", { name: /Minor/ }));
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Publish" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Add at least one page before publishing this module.",
    );
  });

  it("shows a published module's version, its history, and the way back out", async () => {
    const user = userEvent.setup();
    mockBackend({
      "GET /api/content/modules/module-1/versions": { status: 200, body: [VERSION] },
      "POST /api/content/modules/module-1/unpublish": {
        status: 200,
        body: { ...PUBLISHED, status: "draft" },
      },
    });
    const onChanged = renderPanel(PUBLISHED);

    expect(
      screen.getByText(
        "Published as version 1. Learners read that version, not the draft above.",
      ),
    ).toBeInTheDocument();
    expect(await screen.findByText("Version 1")).toBeInTheDocument();
    expect(screen.getByText("3 pages")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Unpublish" }));

    await waitFor(() =>
      expect(onChanged).toHaveBeenCalledWith({ ...PUBLISHED, status: "draft" }),
    );
  });

  it("offers no unpublish on a module that was never published", () => {
    mockBackend({ "GET /api/content/modules/module-1/versions": { status: 200, body: [] } });
    renderPanel(MODULE);

    expect(screen.queryByRole("button", { name: "Unpublish" })).not.toBeInTheDocument();
    expect(screen.getByText("Draft. Nothing here has reached a learner yet.")).toBeInTheDocument();
  });

  it("puts a module on the open catalog, and takes it off again", async () => {
    const user = userEvent.setup();
    const requested = mockBackend({
      "GET /api/content/modules/module-1/versions": { status: 200, body: [] },
      "PATCH /api/content/modules/module-1": {
        status: 200,
        body: { ...PUBLISHED, catalog_visible: true },
      },
    });
    const onChanged = renderPanel(PUBLISHED);

    const toggle = screen.getByRole("checkbox", { name: /Show in the open catalog/ });
    // Off unless somebody says otherwise — the deny is the default, not a
    // decision an author has to remember to make.
    expect(toggle).not.toBeChecked();

    await user.click(toggle);

    await waitFor(() =>
      expect(
        requested.find((request) => request.key === "PATCH /api/content/modules/module-1")?.body,
      ).toEqual({ catalog_visible: true }),
    );
    expect(onChanged).toHaveBeenCalledWith({ ...PUBLISHED, catalog_visible: true });
  });

  it("duplicating opens the copy, named as one", async () => {
    const user = userEvent.setup();
    const requested = mockBackend({
      "GET /api/content/modules/module-1/versions": { status: 200, body: [] },
      "POST /api/content/modules/module-1/duplicate": {
        status: 201,
        body: { ...MODULE, id: "module-2", title: "Phishing Awareness (copy)" },
      },
    });
    renderPanel(MODULE);

    await user.click(screen.getByRole("button", { name: "Duplicate" }));

    expect(await screen.findByText("The copy")).toBeInTheDocument();
    expect(
      requested.find((request) => request.key === "POST /api/content/modules/module-1/duplicate")
        ?.body,
    ).toEqual({ title: "Phishing Awareness (copy)" });
  });
  it("names how many learners a substantive revision would send back", async () => {
    const user = userEvent.setup();
    mockBackend({
      "GET /api/content/modules/module-1/versions": { status: 200, body: [VERSION] },
      "GET /api/content/modules/module-1/revision-impact": {
        status: 200,
        body: { completed_learners: 12, in_progress_learners: 3 },
      },
    });
    renderPanel(PUBLISHED);

    await user.click(screen.getByRole("button", { name: "Publish changes" }));
    const dialog = await screen.findByRole("dialog");

    // Not before the author has chosen: a warning standing next to the
    // question is noise, and noise is how a warning stops being read.
    expect(within(dialog).queryByText(/will be sent back/)).not.toBeInTheDocument();

    await user.click(within(dialog).getByRole("radio", { name: /Substantive/ }));

    const warning = await within(dialog).findByText(/15 learners will be sent back/);
    expect(warning).toHaveTextContent("12 who completed it");
    expect(warning).toHaveTextContent("3 part-way through");
    // The count is a reason to think, not a reason to stop.
    expect(within(dialog).getByRole("button", { name: "Publish" })).toBeEnabled();
  });

  it("does not warn about a substantive revision nobody has read", async () => {
    const user = userEvent.setup();
    mockBackend({
      "GET /api/content/modules/module-1/versions": { status: 200, body: [] },
      "GET /api/content/modules/module-1/revision-impact": {
        status: 200,
        body: { completed_learners: 0, in_progress_learners: 0 },
      },
    });
    renderPanel(MODULE);

    await user.click(screen.getByRole("button", { name: "Publish" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("radio", { name: /Substantive/ }));

    expect(
      await within(dialog).findByText(/Nobody has opened this module yet/),
    ).toBeInTheDocument();
  });

  it("a minor revision is never given a blast radius", async () => {
    const user = userEvent.setup();
    mockBackend({
      "GET /api/content/modules/module-1/versions": { status: 200, body: [VERSION] },
      "GET /api/content/modules/module-1/revision-impact": {
        status: 200,
        body: { completed_learners: 12, in_progress_learners: 3 },
      },
    });
    renderPanel(PUBLISHED);

    await user.click(screen.getByRole("button", { name: "Publish changes" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("radio", { name: /Minor/ }));

    expect(within(dialog).queryByText(/will be sent back/)).not.toBeInTheDocument();
  });

  it("publishes even when the impact count cannot be loaded", async () => {
    const user = userEvent.setup();
    const requested = mockBackend({
      "GET /api/content/modules/module-1/versions": { status: 200, body: [] },
      "GET /api/content/modules/module-1/revision-impact": { status: 500 },
      "POST /api/content/modules/module-1/publish": { status: 200, body: PUBLISHED },
    });
    renderPanel(MODULE);

    await user.click(screen.getByRole("button", { name: "Publish" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("radio", { name: /Substantive/ }));
    await user.click(within(dialog).getByRole("button", { name: "Publish" }));

    await waitFor(() =>
      expect(
        requested.find((request) => request.key === "POST /api/content/modules/module-1/publish")
          ?.body,
      ).toEqual({ revision_kind: "substantive" }),
    );
  });
});
