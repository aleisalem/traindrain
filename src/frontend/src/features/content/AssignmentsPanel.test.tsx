import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import i18n from "../../i18n";
import "../../i18n";
import { AssignmentsPanel } from "./AssignmentsPanel";
import type { Assignment, ContentGroup } from "./types";
import type { AssignmentsState } from "./useAssignments";

function group(overrides: Partial<ContentGroup> = {}): ContentGroup {
  return { id: "group-1", name: "Warehouse Staff", description: null, member_count: 4, ...overrides };
}

function assignment(overrides: Partial<Assignment> = {}): Assignment {
  return {
    id: "assignment-1",
    translation_group_id: "group-1",
    target: { type: "group", id: "group-1", name: "Warehouse Staff" },
    due_date: "2026-12-01",
    requirement: "mandatory",
    auto_reminders: true,
    assigned_by: { id: "user-1", display_name: "Cora Manager" },
    created_at: "2026-09-01T00:00:00Z",
    ...overrides,
  };
}

function stateWith(overrides: Partial<AssignmentsState> = {}): AssignmentsState {
  return {
    assignments: [],
    loading: false,
    loadError: false,
    busy: false,
    error: null,
    create: vi.fn().mockResolvedValue(true),
    remove: vi.fn().mockResolvedValue(true),
    clearError: vi.fn(),
    ...overrides,
  };
}

function mockGroups(groups: ContentGroup[]) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.endsWith("/api/content/groups")) {
        return new Response(JSON.stringify(groups), { status: 200 });
      }
      return new Response(JSON.stringify([]), { status: 200 });
    }),
  );
}

function mockGroupsAndRemind(groups: ContentGroup[], remindResponse: Response) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    if (url.endsWith("/remind") && init?.method === "POST") {
      return remindResponse;
    }
    if (url.endsWith("/api/content/groups")) {
      return new Response(JSON.stringify(groups), { status: 200 });
    }
    return new Response(JSON.stringify([]), { status: 200 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("AssignmentsPanel", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("en");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("lists the module's current assignments with their due date and requirement", async () => {
    mockGroups([]);
    const assignments = stateWith({ assignments: [assignment()] });

    render(
      <AssignmentsPanel moduleId="module-1" assignments={assignments} isAdministrator={false} />,
    );

    expect(await screen.findByText("Group: Warehouse Staff")).toBeInTheDocument();
    expect(screen.getByText("Mandatory · Due 2026-12-01")).toBeInTheDocument();
  });

  it("hides an individual target's identity from a Content Manager", async () => {
    mockGroups([]);
    const assignments = stateWith({
      assignments: [
        assignment({
          target: { type: "user", id: "user-9", name: null },
        }),
      ],
    });

    render(
      <AssignmentsPanel moduleId="module-1" assignments={assignments} isAdministrator={false} />,
    );

    expect(await screen.findByText("An individual")).toBeInTheDocument();
  });

  it("only offers the individual target option to an Administrator", async () => {
    mockGroups([group()]);
    const cmAssignments = stateWith();
    const { unmount } = render(
      <AssignmentsPanel moduleId="module-1" assignments={cmAssignments} isAdministrator={false} />,
    );
    expect(screen.queryByText("Individual")).not.toBeInTheDocument();
    unmount();

    const adminAssignments = stateWith();
    render(
      <AssignmentsPanel moduleId="module-1" assignments={adminAssignments} isAdministrator={true} />,
    );
    expect(await screen.findByText("Individual")).toBeInTheDocument();
  });

  it("assigns the module to the chosen group with the chosen requirement", async () => {
    mockGroups([group()]);
    const user = userEvent.setup();
    const assignments = stateWith();

    render(
      <AssignmentsPanel moduleId="module-1" assignments={assignments} isAdministrator={false} />,
    );

    await user.selectOptions(
      await screen.findByRole("combobox", { name: "Group" }),
      "group-1",
    );
    await user.selectOptions(screen.getByRole("combobox", { name: "Requirement" }), "recommended");
    await user.click(screen.getByRole("button", { name: "Assign" }));

    expect(assignments.create).toHaveBeenCalledWith({
      targetType: "group",
      targetId: "group-1",
      dueDate: null,
      requirement: "recommended",
      autoReminders: true,
    });
  });

  it("removes an assignment when asked", async () => {
    mockGroups([]);
    const user = userEvent.setup();
    const assignments = stateWith({ assignments: [assignment()] });

    render(
      <AssignmentsPanel moduleId="module-1" assignments={assignments} isAdministrator={false} />,
    );
    await user.click(await screen.findByRole("button", { name: "Remove" }));

    expect(assignments.remove).toHaveBeenCalledWith("assignment-1");
  });

  it("shows the server's refusal", async () => {
    mockGroups([]);
    const assignments = stateWith({ error: "This module is already assigned to this target." });

    render(
      <AssignmentsPanel moduleId="module-1" assignments={assignments} isAdministrator={false} />,
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This module is already assigned to this target.",
    );
  });

  it("only offers the manual nudge to an Administrator", async () => {
    mockGroups([]);
    const cmAssignments = stateWith();
    const { unmount } = render(
      <AssignmentsPanel moduleId="module-1" assignments={cmAssignments} isAdministrator={false} />,
    );
    expect(screen.queryByRole("button", { name: "Remind everyone outstanding" })).not.toBeInTheDocument();
    unmount();

    const adminAssignments = stateWith();
    render(
      <AssignmentsPanel moduleId="module-1" assignments={adminAssignments} isAdministrator={true} />,
    );
    expect(
      await screen.findByRole("button", { name: "Remind everyone outstanding" }),
    ).toBeInTheDocument();
  });

  it("nudges outstanding learners and reports how many were reminded", async () => {
    const fetchMock = mockGroupsAndRemind(
      [],
      new Response(JSON.stringify({ sent_count: 3 }), { status: 200 }),
    );
    const user = userEvent.setup();
    const assignments = stateWith();

    render(
      <AssignmentsPanel moduleId="module-1" assignments={assignments} isAdministrator={true} />,
    );
    await user.click(await screen.findByRole("button", { name: "Remind everyone outstanding" }));

    expect(await screen.findByText("Reminded 3 learners.")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/content/modules/module-1/remind",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("shows the daily rate limit when the module was already nudged today", async () => {
    mockGroupsAndRemind(
      [],
      new Response(
        JSON.stringify({ detail: { code: "reminder_already_sent_today" } }),
        { status: 429 },
      ),
    );
    const user = userEvent.setup();
    const assignments = stateWith();

    render(
      <AssignmentsPanel moduleId="module-1" assignments={assignments} isAdministrator={true} />,
    );
    await user.click(await screen.findByRole("button", { name: "Remind everyone outstanding" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This module has already been nudged today.",
    );
  });
});
