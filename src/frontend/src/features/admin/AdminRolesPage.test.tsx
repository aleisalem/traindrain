import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import i18n from "../../i18n";
import "../../i18n";
import { AdminRolesPage } from "./AdminRolesPage";

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

const ROLES = [
  { id: "role-admin", name: "Administrator" },
  { id: "role-content", name: "Content Manager" },
  { id: "role-learner", name: "Learner" },
];

const ADMIN = { id: "admin-1", email: "admin@example.com", roles: ["Administrator"] };
const LEARNER = { id: "learner-1", email: "learner@example.com", roles: ["Learner"] };

function queueInitialLoad(
  queue: ReturnType<typeof createFetchMock>["queue"],
  users: unknown[] = [ADMIN, LEARNER],
) {
  queue("GET", "/api/admin/roles", { status: 200, body: ROLES });
  queue("GET", "/api/admin/users", { status: 200, body: users });
}

describe("AdminRolesPage", () => {
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

  it("lists each role with its current members", async () => {
    queueInitialLoad(queue);

    render(<AdminRolesPage />);

    const adminHeading = await screen.findByText("Administrator");
    const adminSection = adminHeading.closest("div")!;
    expect(within(adminSection).getByText("admin@example.com")).toBeInTheDocument();

    const learnerHeading = screen.getByText("Learner");
    const learnerSection = learnerHeading.closest("div")!;
    expect(within(learnerSection).getByText("learner@example.com")).toBeInTheDocument();

    const contentHeading = screen.getByText("Content Manager");
    const contentSection = contentHeading.closest("div")!;
    expect(within(contentSection).getByText("No users hold this role yet.")).toBeInTheDocument();
  });

  it("assigns a role to a user and refreshes the member list", async () => {
    const user = userEvent.setup();
    queueInitialLoad(queue);
    queue("POST", "/api/admin/users/learner-1/roles/role-content", { status: 204 });
    queueInitialLoad(queue, [ADMIN, { ...LEARNER, roles: ["Learner", "Content Manager"] }]);

    render(<AdminRolesPage />);
    const contentHeading = await screen.findByText("Content Manager");
    const contentSection = contentHeading.closest("div")!;

    await user.selectOptions(
      within(contentSection).getByLabelText("Add user:"),
      "learner-1",
    );
    await user.click(within(contentSection).getByRole("button", { name: "Assign" }));

    expect(await within(contentSection).findByText("learner@example.com")).toBeInTheDocument();
  });

  it("removes a role from a user and refreshes the member list", async () => {
    const user = userEvent.setup();
    queueInitialLoad(queue);
    queue("DELETE", "/api/admin/users/learner-1/roles/role-learner", { status: 204 });
    queueInitialLoad(queue, [ADMIN, { ...LEARNER, roles: [] }]);

    render(<AdminRolesPage />);
    const learnerHeading = await screen.findByText("Learner");
    const learnerSection = learnerHeading.closest("div")!;
    await within(learnerSection).findByText("learner@example.com");

    await user.click(within(learnerSection).getByRole("button", { name: "Remove" }));

    expect(await within(learnerSection).findByText("No users hold this role yet.")).toBeInTheDocument();
  });

  it("shows a conflict message when assigning a role fails", async () => {
    const user = userEvent.setup();
    queueInitialLoad(queue);
    queue("POST", "/api/admin/users/learner-1/roles/role-content", { status: 409 });

    render(<AdminRolesPage />);
    const contentHeading = await screen.findByText("Content Manager");
    const contentSection = contentHeading.closest("div")!;

    await user.selectOptions(
      within(contentSection).getByLabelText("Add user:"),
      "learner-1",
    );
    await user.click(within(contentSection).getByRole("button", { name: "Assign" }));

    expect(await within(contentSection).findByRole("alert")).toHaveTextContent(
      "This user already has this role.",
    );
  });

  it("shows an error message when roles fail to load", async () => {
    queue("GET", "/api/admin/roles", { status: 500 });
    queue("GET", "/api/admin/users", { status: 200, body: [ADMIN, LEARNER] });

    render(<AdminRolesPage />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Could not load roles. Please try again.",
    );
  });
});
