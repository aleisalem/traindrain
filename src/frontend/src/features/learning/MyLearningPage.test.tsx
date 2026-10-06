import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import i18n from "../../i18n";
import "../../i18n";
import { MyLearningPage } from "./MyLearningPage";
import type { LearnerCampaign, LearnerModuleSummary } from "./types";

function summary(id: string, title: string): LearnerModuleSummary {
  return {
    translation_group_id: id,
    title,
    language: "en",
    estimated_duration_minutes: null,
    started_at: "2026-09-01T00:00:00Z",
    completed_at: null,
    completed_version_number: null,
    superseded_at: null,
    available: true,
    due_date: null,
    requirement: null,
    overdue: false,
  };
}

const CAMPAIGN: LearnerCampaign = {
  id: "c1",
  name: "Phishing programme",
  description: null,
  status: "active",
  due_date: "2020-01-01",
  overdue: true,
  required_total: 5,
  required_done: 3,
  complete: false,
  modules: [
    { translation_group_id: "g1", position: 0, title: "Spot a phish", requirement: "mandatory", state: "completed", available: true, overdue: false },
    { translation_group_id: "g2", position: 1, title: "Report a phish", requirement: "mandatory", state: "not_started", available: true, overdue: true },
    { translation_group_id: "g3", position: 2, title: "Bonus reading", requirement: "recommended", state: "not_started", available: false, overdue: false },
  ],
};

function stub(campaigns: LearnerCampaign[] | "error", modules: LearnerModuleSummary[]) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (url === "/api/me/campaigns") {
        return campaigns === "error"
          ? new Response("{}", { status: 500 })
          : new Response(JSON.stringify(campaigns));
      }
      return new Response(JSON.stringify(modules));
    }),
  );
}

function renderPage() {
  return render(
    <MemoryRouter>
      <MyLearningPage />
    </MemoryRouter>,
  );
}

describe("MyLearningPage campaigns", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("en");
  });
  afterEach(() => vi.unstubAllGlobals());

  it("groups modules under their campaign with a progress bar and badges", async () => {
    stub([CAMPAIGN], [summary("g1", "Spot a phish"), summary("g9", "Fire safety")]);
    renderPage();

    const bar = await screen.findByRole("progressbar", { name: "3 of 5 required done" });
    expect(bar).toHaveAttribute("aria-valuenow", "3");
    expect(bar).toHaveAttribute("aria-valuemax", "5");

    const card = bar.closest("li") as HTMLElement;
    expect(within(card).getByText("Overdue")).toBeInTheDocument();
    expect(within(card).getByText(/Due 2020-01-01/)).toBeInTheDocument();
    expect(within(card).getByText(/Mandatory · Completed/)).toBeInTheDocument();
    expect(within(card).getByText(/Recommended · Not started/)).toBeInTheDocument();
    // Not openable through this campaign → no link, an explanation instead.
    expect(within(card).getByText("No longer available")).toBeInTheDocument();
  });

  it("does not list a campaign's module a second time among the other modules", async () => {
    stub([CAMPAIGN], [summary("g1", "Spot a phish"), summary("g9", "Fire safety")]);
    renderPage();
    await screen.findByRole("progressbar");
    expect(screen.getAllByText("Spot a phish")).toHaveLength(1);
    expect(screen.getByText("Fire safety")).toBeInTheDocument();
    expect(screen.getByText("Other learning")).toBeInTheDocument();
  });

  it("still shows the module list when only the campaign request fails", async () => {
    stub("error", [summary("g9", "Fire safety")]);
    renderPage();
    expect(await screen.findByText("Fire safety")).toBeInTheDocument();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  });

  it("shows the empty state when there are no campaigns and no modules", async () => {
    stub([], []);
    renderPage();
    expect(await screen.findByRole("link", { name: "Find something to read" })).toBeInTheDocument();
  });
});
