import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

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
    // no globals stubbed here
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
});
