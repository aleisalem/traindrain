import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import i18n from "../../i18n";
import "../../i18n";
import { ModuleReportsPage } from "./ModuleReportsPage";

const MODULES = [
  {
    id: "module-1",
    translation_group_id: "group-1",
    language: "en",
    title: "Fire Safety",
    description: "Exits and extinguishers.",
    estimated_duration_minutes: 10,
    status: "published",
    catalog_visible: true,
    current_version_number: 1,
    tags: [],
    created_by: { id: "user-1", display_name: "Cora Manager" },
    last_edited_by: { id: "user-1", display_name: "Cora Manager" },
    created_at: "2026-09-01T00:00:00Z",
    updated_at: "2026-09-01T00:00:00Z",
  },
  {
    id: "module-2",
    translation_group_id: "group-2",
    language: "en",
    title: "Phishing Awareness",
    description: "Spotting a phish.",
    estimated_duration_minutes: 15,
    status: "draft",
    catalog_visible: false,
    current_version_number: null,
    tags: [],
    created_by: { id: "user-1", display_name: "Cora Manager" },
    last_edited_by: { id: "user-1", display_name: "Cora Manager" },
    created_at: "2026-09-02T00:00:00Z",
    updated_at: "2026-09-02T00:00:00Z",
  },
];

function mockFetch(reportBody: unknown = { translation_group_id: "group-1", groups: [] }) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input.toString();
    if (url === "/api/content/modules") {
      return new Response(JSON.stringify(MODULES), { status: 200 });
    }
    if (url.endsWith("/report")) {
      return new Response(JSON.stringify(reportBody), { status: 200 });
    }
    return new Response(JSON.stringify(null), { status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("ModuleReportsPage", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("en");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("lists every module, searchable by title or description", async () => {
    mockFetch();
    const user = userEvent.setup();

    render(<ModuleReportsPage isAdministrator={false} />);

    expect(await screen.findByText("Fire Safety")).toBeInTheDocument();
    expect(screen.getByText("Phishing Awareness")).toBeInTheDocument();

    await user.type(screen.getByLabelText("Search modules"), "phish");

    expect(screen.queryByText("Fire Safety")).not.toBeInTheDocument();
    expect(screen.getByText("Phishing Awareness")).toBeInTheDocument();
  });

  it("shows a message when nothing matches the search", async () => {
    mockFetch();
    const user = userEvent.setup();

    render(<ModuleReportsPage isAdministrator={false} />);
    await screen.findByText("Fire Safety");
    await user.type(screen.getByLabelText("Search modules"), "nonexistent module");

    expect(screen.getByText("No modules match your search.")).toBeInTheDocument();
  });

  it("shows the selected module's report", async () => {
    mockFetch({
      translation_group_id: "group-1",
      groups: [
        {
          group_id: "g1",
          group_name: "Warehouse Staff",
          member_count: 3,
          completed: 1,
          in_progress: 1,
          not_started: 1,
          overdue: 0,
        },
      ],
    });
    const user = userEvent.setup();

    render(<ModuleReportsPage isAdministrator={false} />);
    await user.click(await screen.findByText("Fire Safety"));

    expect(await screen.findByText(/Warehouse Staff/)).toBeInTheDocument();
    // The selected module's title is shown above its report.
    expect(screen.getAllByText("Fire Safety").length).toBeGreaterThan(1);
  });

  it("hides the report again when the selected module is clicked a second time", async () => {
    mockFetch();
    const user = userEvent.setup();

    render(<ModuleReportsPage isAdministrator={false} />);
    const row = await screen.findByText("Fire Safety");
    await user.click(row);
    await waitFor(() => expect(screen.getByText("Report")).toBeInTheDocument());

    await user.click(screen.getByText("Fire Safety", { selector: "span.font-medium" }));

    expect(screen.queryByText("Report")).not.toBeInTheDocument();
  });

  it("offers the CSV export only to an Administrator", async () => {
    mockFetch();
    const user = userEvent.setup();

    render(<ModuleReportsPage isAdministrator={true} />);
    await user.click(await screen.findByText("Fire Safety"));

    expect(await screen.findByRole("link", { name: "Export CSV" })).toHaveAttribute(
      "href",
      "/api/content/modules/module-1/report.csv",
    );
  });

  it("shows the server's load failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(null, { status: 500 })),
    );

    render(<ModuleReportsPage isAdministrator={false} />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "We couldn't load this. Please try again.",
    );
  });
});
