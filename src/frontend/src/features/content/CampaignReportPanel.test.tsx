import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import "../../i18n";
import { CampaignReportPanel } from "./CampaignReportPanel";
import type {
  AdministratorCampaignReport,
  ContentManagerCampaignReport,
} from "./types";
import type { CampaignReportState } from "./useCampaignReport";

const MODULES = [
  { translation_group_id: "g1", title: "Fire Safety", requirement: "mandatory" as const, unavailable: false },
  { translation_group_id: "g2", title: "Phishing", requirement: "recommended" as const, unavailable: false },
];

function stateWith(report: CampaignReportState["report"], overrides: Partial<CampaignReportState> = {}) {
  return { report, loading: false, loadError: false, reload: async () => {}, ...overrides };
}

const cm: ContentManagerCampaignReport = {
  campaign_id: "c1",
  campaign_name: "Onboarding",
  status: "active",
  due_date: null,
  modules: MODULES,
  groups: [
    {
      group_id: "t1",
      group_name: "Warehouse Staff",
      member_count: 4,
      completed: 1,
      in_progress: 1,
      not_started: 1,
      overdue: 2,
      suspended: 1,
      average_progress: 40,
    },
  ],
};

const admin: AdministratorCampaignReport = {
  campaign_id: "c1",
  campaign_name: "Onboarding",
  status: "active",
  due_date: null,
  modules: MODULES,
  learners: [
    {
      user_id: "u1",
      name: "Lena Learner",
      email: "lena@example.com",
      state: "in_progress",
      overdue: true,
      required_total: 1,
      required_done: 0,
      progress_percent: 0,
      modules: [
        {
          translation_group_id: "g1",
          requirement: "mandatory",
          state: "in_progress",
          unavailable: false,
          completed_at: "2026-10-01T00:00:00Z",
          completed_version_number: 1,
        },
        {
          translation_group_id: "g2",
          requirement: "recommended",
          state: "not_started",
          unavailable: true,
          completed_at: null,
          completed_version_number: null,
        },
      ],
    },
  ],
};

describe("CampaignReportPanel", () => {
  it("shows a Content Manager group counts and average progress, never a name or CSV link", () => {
    render(<CampaignReportPanel campaignId="c1" report={stateWith(cm)} isAdministrator={false} />);

    expect(screen.getByText(/Warehouse Staff/)).toBeInTheDocument();
    expect(screen.getByText("Suspended", { selector: "th" })).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: /Warehouse Staff/ })).toHaveAttribute(
      "aria-valuenow",
      "40",
    );
    expect(screen.queryByRole("link", { name: /export csv/i })).not.toBeInTheDocument();
    expect(screen.queryByText("lena@example.com")).not.toBeInTheDocument();
  });

  it("shows an Administrator the roster, per-module state, and the CSV link", () => {
    render(<CampaignReportPanel campaignId="c1" report={stateWith(admin)} isAdministrator />);

    expect(screen.getByText("Lena Learner")).toBeInTheDocument();
    expect(screen.getByText("lena@example.com")).toBeInTheDocument();
    expect(screen.getByText("Fire Safety")).toBeInTheDocument();
    expect(screen.getByText(/Completed v1 earlier/)).toBeInTheDocument();
    expect(screen.getByText("Unavailable")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /export csv/i })).toHaveAttribute(
      "href",
      "/api/content/campaigns/c1/report.csv",
    );
  });

  it("explains a suspended campaign and reports a load failure", () => {
    const { rerender } = render(
      <CampaignReportPanel
        campaignId="c1"
        report={stateWith({ ...cm, status: "suspended" })}
        isAdministrator={false}
      />,
    );
    expect(screen.getByRole("status")).toHaveTextContent(/suspended/i);

    rerender(
      <CampaignReportPanel
        campaignId="c1"
        report={stateWith(null, { loadError: true })}
        isAdministrator={false}
      />,
    );
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });
});
