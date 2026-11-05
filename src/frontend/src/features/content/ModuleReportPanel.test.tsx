import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import i18n from "../../i18n";
import "../../i18n";
import { ModuleReportPanel } from "./ModuleReportPanel";
import type {
  AdministratorModuleReport,
  ContentManagerModuleReport,
} from "./types";
import type { ModuleReportState } from "./useModuleReport";

function stateWith(overrides: Partial<ModuleReportState> = {}): ModuleReportState {
  return {
    report: null,
    loading: false,
    loadError: false,
    reload: async () => {},
    ...overrides,
  };
}

function cmReport(overrides: Partial<ContentManagerModuleReport> = {}): ContentManagerModuleReport {
  return {
    translation_group_id: "group-1",
    groups: [
      {
        group_id: "target-group-1",
        group_name: "Warehouse Staff",
        member_count: 3,
        completed: 1,
        in_progress: 1,
        not_started: 1,
        overdue: 2,
      },
    ],
    ...overrides,
  };
}

function adminReport(overrides: Partial<AdministratorModuleReport> = {}): AdministratorModuleReport {
  return {
    translation_group_id: "group-1",
    learners: [
      {
        user_id: "user-1",
        name: "Lena Learner",
        email: "lena@example.com",
        state: "completed",
        overdue: false,
        due_date: "2026-12-01",
        completed_at: "2026-11-01T00:00:00Z",
        completed_version_number: 2,
      },
    ],
    ...overrides,
  };
}

describe("ModuleReportPanel", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("en");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows a Content Manager per-group counts with no identities and no CSV export", () => {
    render(
      <ModuleReportPanel
        moduleId="module-1"
        report={stateWith({ report: cmReport() })}
        isAdministrator={false}
      />,
    );

    expect(screen.getByText(/Warehouse Staff/)).toBeInTheDocument();
    expect(screen.getByText("(3 members)")).toBeInTheDocument();
    // The overdue count (2) is the only unique cell value in this fixture.
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.queryByText("Export CSV")).not.toBeInTheDocument();
    expect(screen.queryByText("lena@example.com")).not.toBeInTheDocument();
  });

  it("shows an Administrator the full roster with a CSV export link", () => {
    render(
      <ModuleReportPanel
        moduleId="module-1"
        report={stateWith({ report: adminReport() })}
        isAdministrator={true}
      />,
    );

    expect(screen.getByText("Lena Learner")).toBeInTheDocument();
    expect(screen.getByText("lena@example.com")).toBeInTheDocument();
    expect(screen.getByText("v2")).toBeInTheDocument();
    const exportLink = screen.getByRole("link", { name: "Export CSV" });
    expect(exportLink).toHaveAttribute("href", "/api/content/modules/module-1/report.csv");
  });

  it("never offers the CSV export to a Content Manager even if the roster shape somehow arrived", () => {
    render(
      <ModuleReportPanel
        moduleId="module-1"
        report={stateWith({ report: adminReport() })}
        isAdministrator={false}
      />,
    );

    expect(screen.queryByRole("link", { name: "Export CSV" })).not.toBeInTheDocument();
  });

  it("flags an overdue learner on the roster", () => {
    render(
      <ModuleReportPanel
        moduleId="module-1"
        report={stateWith({
          report: adminReport({
            learners: [
              {
                user_id: "user-2",
                name: "Otto Overdue",
                email: "otto@example.com",
                state: "not_started",
                overdue: true,
                due_date: "2026-01-01",
                completed_at: null,
                completed_version_number: null,
              },
            ],
          }),
        })}
        isAdministrator={true}
      />,
    );

    expect(screen.getByText("Overdue")).toBeInTheDocument();
  });

  it("shows the server's load failure", () => {
    render(
      <ModuleReportPanel
        moduleId="module-1"
        report={stateWith({ loadError: true })}
        isAdministrator={false}
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent(
      "We couldn't load this. Please try again.",
    );
  });

  it("renders nothing while loading", () => {
    const { container } = render(
      <ModuleReportPanel
        moduleId="module-1"
        report={stateWith({ loading: true, report: null })}
        isAdministrator={false}
      />,
    );

    expect(container).toBeEmptyDOMElement();
  });

  it("lets an Administrator reset a learner's quiz attempts after confirming", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ attempts_deleted: 2 }),
    });
    vi.stubGlobal("fetch", fetchMock);
    render(
      <ModuleReportPanel
        moduleId="module-1"
        report={stateWith({ report: adminReport() })}
        isAdministrator={true}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Reset attempts for Lena Learner" }));
    // Nothing is sent until the second click.
    expect(fetchMock).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Delete Lena Learner's attempts" }));

    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent("2 attempts deleted"),
    );
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/content/modules/module-1/quiz/attempts/reset",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ user_id: "user-1" }) }),
    );
  });

  it("can back out of a reset without sending anything", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    render(
      <ModuleReportPanel
        moduleId="module-1"
        report={stateWith({ report: adminReport() })}
        isAdministrator={true}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Reset attempts for Lena Learner" }));
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(fetchMock).not.toHaveBeenCalled();
    expect(
      screen.getByRole("button", { name: "Reset attempts for Lena Learner" }),
    ).toBeInTheDocument();
  });

  it("offers no reset control to a Content Manager", () => {
    render(
      <ModuleReportPanel
        moduleId="module-1"
        report={stateWith({ report: cmReport() })}
        isAdministrator={false}
      />,
    );
    expect(screen.queryByRole("button", { name: /Reset attempts/ })).not.toBeInTheDocument();
  });
});
