import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import i18n from "../../i18n";
import "../../i18n";
import { AdminGroupsPage } from "./AdminGroupsPage";

type MockResponse = { status: number; body?: unknown };

function createFetchMock() {
  const queues = new Map<string, MockResponse[]>();

  function queue(method: string, url: string, response: MockResponse) {
    const key = `${method} ${url}`;
    const existing = queues.get(key) ?? [];
    existing.push(response);
    queues.set(key, existing);
  }

  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    const method = init?.method ?? "GET";
    const key = `${method} ${url}`;
    const queued = queues.get(key)?.shift();
    if (!queued) throw new Error(`No mocked response queued for ${key}`);
    const hasBody = ![204, 205, 304].includes(queued.status);
    return new Response(hasBody ? JSON.stringify(queued.body) : null, {
      status: queued.status,
      headers: hasBody ? { "Content-Type": "application/json" } : {},
    });
  });

  return { fetchMock, queue };
}

const GROUPS = [
  { id: "group-sales", name: "Sales Team", description: "All sales reps", created_at: "2026-01-01T00:00:00Z" },
  { id: "group-eng", name: "Engineering", description: null, created_at: "2026-01-01T00:00:00Z" },
];

const USERS = [
  { id: "user-1", email: "ada@example.com" },
  { id: "user-2", email: "grace@example.com" },
];

function queueInitialLoad(
  queue: ReturnType<typeof createFetchMock>["queue"],
  options: {
    groups?: typeof GROUPS;
    users?: typeof USERS;
    membersByGroup?: Record<string, typeof USERS>;
  } = {},
) {
  const groups = options.groups ?? GROUPS;
  const users = options.users ?? USERS;
  const membersByGroup = options.membersByGroup ?? {};
  queue("GET", "/api/admin/groups", { status: 200, body: groups });
  queue("GET", "/api/admin/users", { status: 200, body: users });
  for (const group of groups) {
    queue("GET", `/api/admin/groups/${group.id}/members`, {
      status: 200,
      body: membersByGroup[group.id] ?? [],
    });
  }
}

describe("AdminGroupsPage", () => {
  let queue: ReturnType<typeof createFetchMock>["queue"];

  beforeEach(async () => {
    await i18n.changeLanguage("en");
    const mock = createFetchMock();
    queue = mock.queue;
    vi.stubGlobal("fetch", mock.fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("lists each group with its current members", async () => {
    queueInitialLoad(queue, {
      membersByGroup: { "group-sales": [USERS[0]] },
    });

    render(<AdminGroupsPage />);

    const salesHeading = await screen.findByText("Sales Team");
    const salesSection = salesHeading.closest("div.rounded-lg") as HTMLElement;
    expect(within(salesSection).getByText("ada@example.com")).toBeInTheDocument();

    const engHeading = screen.getByText("Engineering");
    const engSection = engHeading.closest("div.rounded-lg") as HTMLElement;
    expect(within(engSection).getByText("No users belong to this group yet.")).toBeInTheDocument();
  });

  it("creates a new group", async () => {
    const user = userEvent.setup();
    queueInitialLoad(queue);
    queue("POST", "/api/admin/groups", {
      status: 201,
      body: { id: "group-new", name: "Marketing", description: null, created_at: "2026-01-01T00:00:00Z" },
    });
    queueInitialLoad(queue, { groups: [...GROUPS, { id: "group-new", name: "Marketing", description: null, created_at: "2026-01-01T00:00:00Z" }] });

    render(<AdminGroupsPage />);
    await screen.findByText("Sales Team");

    await user.type(screen.getByLabelText("Name"), "Marketing");
    await user.click(screen.getByRole("button", { name: "Create group" }));

    expect(await screen.findByText("Marketing")).toBeInTheDocument();
  });

  it("shows a conflict message when creating a group with a duplicate name", async () => {
    const user = userEvent.setup();
    queueInitialLoad(queue);
    queue("POST", "/api/admin/groups", { status: 409 });

    render(<AdminGroupsPage />);
    await screen.findByText("Sales Team");

    await user.type(screen.getByLabelText("Name"), "Sales Team");
    await user.click(screen.getByRole("button", { name: "Create group" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "A group with this name already exists.",
    );
  });

  it("adds a member to a group and refreshes the member list", async () => {
    const user = userEvent.setup();
    queueInitialLoad(queue);
    queue("POST", "/api/admin/groups/group-eng/members/user-2", { status: 204 });
    queueInitialLoad(queue, { membersByGroup: { "group-eng": [USERS[1]] } });

    render(<AdminGroupsPage />);
    const engHeading = await screen.findByText("Engineering");
    const engSection = engHeading.closest("div.rounded-lg") as HTMLElement;

    await user.selectOptions(within(engSection).getByLabelText("Add user:"), "user-2");
    await user.click(within(engSection).getByRole("button", { name: "Add" }));

    expect(await within(engSection).findByText("grace@example.com")).toBeInTheDocument();
  });

  it("removes a member from a group and refreshes the member list", async () => {
    const user = userEvent.setup();
    queueInitialLoad(queue, { membersByGroup: { "group-sales": [USERS[0]] } });
    queue("DELETE", "/api/admin/groups/group-sales/members/user-1", { status: 204 });
    queueInitialLoad(queue);

    render(<AdminGroupsPage />);
    const salesHeading = await screen.findByText("Sales Team");
    const salesSection = salesHeading.closest("div.rounded-lg") as HTMLElement;
    await within(salesSection).findByText("ada@example.com");

    await user.click(within(salesSection).getByRole("button", { name: "Remove" }));

    expect(
      await within(salesSection).findByText("No users belong to this group yet."),
    ).toBeInTheDocument();
  });

  it("edits a group's name and description", async () => {
    const user = userEvent.setup();
    queueInitialLoad(queue);
    queue("PUT", "/api/admin/groups/group-eng", {
      status: 200,
      body: { id: "group-eng", name: "Platform Engineering", description: "Renamed", created_at: "2026-01-01T00:00:00Z" },
    });
    queueInitialLoad(queue, {
      groups: [GROUPS[0], { id: "group-eng", name: "Platform Engineering", description: "Renamed", created_at: "2026-01-01T00:00:00Z" }],
    });

    render(<AdminGroupsPage />);
    const engHeading = await screen.findByText("Engineering");
    const engSection = engHeading.closest("div.rounded-lg") as HTMLElement;

    await user.click(within(engSection).getByRole("button", { name: "Edit" }));
    const nameInput = within(engSection).getByLabelText("Name");
    await user.clear(nameInput);
    await user.type(nameInput, "Platform Engineering");
    await user.click(within(engSection).getByRole("button", { name: "Save" }));

    expect(await screen.findByText("Platform Engineering")).toBeInTheDocument();
  });

  it("deletes a group after confirmation", async () => {
    const user = userEvent.setup();
    queueInitialLoad(queue);
    queue("DELETE", "/api/admin/groups/group-eng", { status: 204 });
    queueInitialLoad(queue, { groups: [GROUPS[0]] });

    render(<AdminGroupsPage />);
    const engHeading = await screen.findByText("Engineering");
    const engSection = engHeading.closest("div.rounded-lg") as HTMLElement;

    await user.click(within(engSection).getByRole("button", { name: "Delete" }));
    await user.click(within(engSection).getByRole("button", { name: "Confirm delete" }));

    expect(screen.queryByText("Engineering")).not.toBeInTheDocument();
  });

  it("shows an error message when groups fail to load", async () => {
    queue("GET", "/api/admin/groups", { status: 500 });
    queue("GET", "/api/admin/users", { status: 200, body: USERS });

    render(<AdminGroupsPage />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Could not load groups. Please try again.",
    );
  });
});
