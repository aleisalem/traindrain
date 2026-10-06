import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import i18n from "../../i18n";
import "../../i18n";
import { CampaignBuilderPage, moveItem } from "./CampaignBuilderPage";
import type { Campaign } from "./types";

const ACTOR = { id: "user-1", display_name: "Cora Manager" };

function moduleBody(groupId: string, title: string, status = "published") {
  return {
    id: `module-${groupId}`,
    translation_group_id: groupId,
    language: "en",
    title,
    description: null,
    estimated_duration_minutes: null,
    status,
    catalog_visible: false,
    current_version_number: null,
    deleted_version_number: null,
    tags: [],
    created_by: ACTOR,
    last_edited_by: ACTOR,
    created_at: "2026-09-01T00:00:00Z",
    updated_at: "2026-09-01T00:00:00Z",
  };
}

const CAMPAIGN: Campaign = {
  id: "camp-1",
  name: "Phishing programme",
  description: null,
  status: "draft",
  sequential: false,
  auto_reminders: true,
  start_date: null,
  due_date: null,
  created_by: ACTOR,
  modules: [
    {
      translation_group_id: "g-basics",
      position: 0,
      requirement: "mandatory",
      title: "Basics",
      availability: "published",
    },
    {
      translation_group_id: "g-draft",
      position: 1,
      requirement: "mandatory",
      title: "Unfinished",
      availability: "unpublished",
    },
  ],
  targets: [{ type: "group", id: "grp-1", name: "Finance" }],
  created_at: "2026-09-01T00:00:00Z",
  updated_at: "2026-09-01T00:00:00Z",
};

type Call = { url: string; method: string; body: unknown };

function stubFetch(calls: Call[], existing: Campaign | null = CAMPAIGN) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      const body = init?.body ? JSON.parse(init.body as string) : undefined;
      calls.push({ url, method, body });
      const json = (data: unknown, status = 200) =>
        new Response(JSON.stringify(data), { status });
      if (url === "/api/content/modules") {
        return json([
          moduleBody("g-basics", "Basics"),
          moduleBody("g-extra", "Extra credit"),
          moduleBody("g-extra", "Extra credit (DE)"),
        ]);
      }
      if (url === "/api/content/groups") {
        return json([
          { id: "grp-1", name: "Finance", description: null, member_count: 4 },
          { id: "grp-2", name: "Warehouse", description: null, member_count: 9 },
        ]);
      }
      if (url === "/api/content/campaigns" && method === "POST") {
        return json({ ...(existing ?? CAMPAIGN), ...body, id: "camp-new" }, 201);
      }
      if (url.startsWith("/api/content/campaigns/")) {
        if (method === "PATCH") return json({ ...(existing ?? CAMPAIGN), name: body.name });
        return existing ? json(existing) : json({ detail: "x" }, 404);
      }
      return json({}, 404);
    }),
  );
}

function renderBuilder(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/content/campaigns/new" element={<CampaignBuilderPage />} />
        <Route path="/content/campaigns/:campaignId" element={<CampaignBuilderPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("moveItem", () => {
  it("moves an item and ignores out-of-range moves", () => {
    expect(moveItem(["a", "b", "c"], 0, 2)).toEqual(["b", "c", "a"]);
    expect(moveItem(["a", "b", "c"], 2, 0)).toEqual(["c", "a", "b"]);
    expect(moveItem(["a", "b"], 0, 5)).toEqual(["a", "b"]);
  });
});

describe("CampaignBuilderPage", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("en");
  });
  afterEach(() => vi.unstubAllGlobals());

  it("loads an existing campaign and flags an unpublished module", async () => {
    stubFetch([]);
    renderBuilder("/content/campaigns/camp-1");

    expect(await screen.findByDisplayValue("Phishing programme")).toBeInTheDocument();
    expect(screen.getByText("Basics")).toBeInTheDocument();
    expect(screen.getByText(/Not published yet/)).toBeInTheDocument();
    expect(screen.getByText("Finance")).toBeInTheDocument();
  });

  it("reorders modules with the move buttons and sends the new order", async () => {
    const calls: Call[] = [];
    stubFetch(calls);
    renderBuilder("/content/campaigns/camp-1");
    await screen.findByDisplayValue("Phishing programme");

    await userEvent.click(screen.getByRole("button", { name: "Move Unfinished up" }));
    await userEvent.click(screen.getByRole("button", { name: "Save campaign" }));

    await waitFor(() => expect(calls.some((c) => c.method === "PATCH")).toBe(true));
    const patch = calls.find((c) => c.method === "PATCH")!;
    expect((patch.body as { modules: { translation_group_id: string }[] }).modules.map(
      (m) => m.translation_group_id,
    )).toEqual(["g-draft", "g-basics"]);
  });

  it("changes a module's requirement", async () => {
    const calls: Call[] = [];
    stubFetch(calls);
    renderBuilder("/content/campaigns/camp-1");
    await screen.findByDisplayValue("Phishing programme");

    await userEvent.selectOptions(
      screen.getByLabelText("Requirement for Basics"),
      "recommended",
    );
    await userEvent.click(screen.getByRole("button", { name: "Save campaign" }));

    await waitFor(() => expect(calls.some((c) => c.method === "PATCH")).toBe(true));
    const patch = calls.find((c) => c.method === "PATCH")!;
    expect((patch.body as { modules: { requirement: string }[] }).modules[0].requirement).toBe(
      "recommended",
    );
  });

  it("offers each translation group once and not ones already added", async () => {
    stubFetch([]);
    renderBuilder("/content/campaigns/camp-1");
    await screen.findByDisplayValue("Phishing programme");

    const picker = screen.getByLabelText("Add a module");
    await waitFor(() => expect(within(picker).getAllByRole("option")).toHaveLength(2));
    expect(within(picker).getByRole("option", { name: "Extra credit" })).toBeInTheDocument();
    expect(within(picker).queryByRole("option", { name: "Basics" })).not.toBeInTheDocument();
  });

  it("adds a group target showing its member count, and removes one", async () => {
    const calls: Call[] = [];
    stubFetch(calls);
    renderBuilder("/content/campaigns/camp-1");
    await screen.findByDisplayValue("Phishing programme");

    const picker = screen.getByLabelText("Add a group");
    await waitFor(() =>
      expect(within(picker).getByRole("option", { name: "Warehouse (9 members)" })).toBeInTheDocument(),
    );
    await userEvent.selectOptions(picker, "grp-2");
    await userEvent.click(screen.getByRole("button", { name: "Add group" }));
    await userEvent.click(screen.getByRole("button", { name: "Remove Finance" }));
    await userEvent.click(screen.getByRole("button", { name: "Save campaign" }));

    await waitFor(() => expect(calls.some((c) => c.method === "PATCH")).toBe(true));
    const patch = calls.find((c) => c.method === "PATCH")!;
    expect((patch.body as { targets: unknown[] }).targets).toEqual([{ type: "group", id: "grp-2" }]);
  });

  it("creates a new campaign and refuses an empty name or backwards dates", async () => {
    const calls: Call[] = [];
    stubFetch(calls, null);
    renderBuilder("/content/campaigns/new");

    await userEvent.click(await screen.findByRole("button", { name: "Create campaign" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Give the campaign a name.");

    await userEvent.type(screen.getByLabelText("Name"), "Onboarding");
    await userEvent.type(screen.getByLabelText("Start date"), "2026-12-01");
    await userEvent.type(screen.getByLabelText("Due date"), "2026-11-01");
    await userEvent.click(screen.getByRole("button", { name: "Create campaign" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/due date cannot be before/i);
    expect(calls.some((c) => c.method === "POST")).toBe(false);

    await userEvent.clear(screen.getByLabelText("Due date"));
    await userEvent.type(screen.getByLabelText("Due date"), "2026-12-31");
    await userEvent.click(screen.getByRole("button", { name: "Create campaign" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    const post = calls.find((c) => c.method === "POST")!;
    expect(post.body).toMatchObject({ name: "Onboarding", start_date: "2026-12-01", due_date: "2026-12-31" });
  });

  it("shows a not-found message for a campaign the server hides", async () => {
    stubFetch([], null);
    renderBuilder("/content/campaigns/someone-elses");
    expect(await screen.findByRole("alert")).toHaveTextContent("This campaign doesn't exist.");
  });

  it("renders in German", async () => {
    await i18n.changeLanguage("de");
    stubFetch([]);
    renderBuilder("/content/campaigns/camp-1");
    expect(await screen.findByRole("button", { name: "Kampagne speichern" })).toBeInTheDocument();
  });
});
