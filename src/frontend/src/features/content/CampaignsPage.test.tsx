import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import i18n from "../../i18n";
import "../../i18n";
import { CampaignsPage } from "./CampaignsPage";

function stub(response: Response) {
  vi.stubGlobal("fetch", vi.fn(async () => response));
}

describe("CampaignsPage", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("en");
  });
  afterEach(() => vi.unstubAllGlobals());

  it("lists campaigns with status, counts and a link to each", async () => {
    stub(
      new Response(
        JSON.stringify([
          {
            id: "c1",
            name: "Phishing programme",
            status: "draft",
            start_date: null,
            due_date: "2026-12-01",
            module_count: 3,
            target_count: 1,
            created_at: "2026-09-01T00:00:00Z",
            updated_at: "2026-09-01T00:00:00Z",
          },
        ]),
      ),
    );
    render(
      <MemoryRouter>
        <CampaignsPage />
      </MemoryRouter>,
    );

    expect(await screen.findByText("Phishing programme")).toBeInTheDocument();
    expect(screen.getByText("Draft")).toBeInTheDocument();
    expect(screen.getByText(/3 modules/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open" })).toHaveAttribute("href", "/content/campaigns/c1");
    expect(screen.getByRole("link", { name: "New campaign" })).toBeInTheDocument();
  });

  it("shows the empty state", async () => {
    stub(new Response("[]"));
    render(
      <MemoryRouter>
        <CampaignsPage />
      </MemoryRouter>,
    );
    expect(await screen.findByText(/No campaigns yet/)).toBeInTheDocument();
  });

  it("shows an error when the list cannot load", async () => {
    stub(new Response("{}", { status: 500 }));
    render(
      <MemoryRouter>
        <CampaignsPage />
      </MemoryRouter>,
    );
    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });
});
