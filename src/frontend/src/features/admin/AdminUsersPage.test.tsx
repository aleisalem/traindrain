import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import i18n from "../../i18n";
import "../../i18n";
import { AdminUsersPage } from "./AdminUsersPage";

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

const ADMIN = {
  id: "admin-1",
  email: "admin@example.com",
  first_name: "Ada",
  last_name: "Admin",
  roles: ["Administrator"],
  disabled_at: null,
  erased_at: null,
};

const LEARNER = {
  id: "learner-1",
  email: "learner@example.com",
  first_name: "Lena",
  last_name: "Learner",
  roles: ["Learner"],
  disabled_at: null,
  erased_at: null,
};

describe("AdminUsersPage", () => {
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

  it("lists users with their status and hides actions on the admin's own row", async () => {
    queue("GET", "/api/admin/users", { status: 200, body: [ADMIN, LEARNER] });

    render(<AdminUsersPage currentUserId="admin-1" />);

    const adminRow = (await screen.findByText("admin@example.com")).closest("tr")!;
    expect(within(adminRow).getByText("This is your account")).toBeInTheDocument();
    expect(within(adminRow).queryByRole("button")).not.toBeInTheDocument();

    const learnerRow = screen.getByText("learner@example.com").closest("tr")!;
    expect(within(learnerRow).getByText("Active")).toBeInTheDocument();
    expect(within(learnerRow).getByRole("button", { name: "Disable" })).toBeInTheDocument();
    expect(within(learnerRow).getByRole("button", { name: "Erase" })).toBeInTheDocument();
  });

  it("disables a user and refreshes the list to show the new status", async () => {
    const user = userEvent.setup();
    queue("GET", "/api/admin/users", { status: 200, body: [ADMIN, LEARNER] });
    queue("POST", "/api/admin/users/learner-1/disable", { status: 204 });
    queue("GET", "/api/admin/users", {
      status: 200,
      body: [ADMIN, { ...LEARNER, disabled_at: "2026-09-05T00:00:00Z" }],
    });

    render(<AdminUsersPage currentUserId="admin-1" />);
    await screen.findByText("learner@example.com");

    const learnerRow = screen.getByText("learner@example.com").closest("tr")!;
    await user.click(within(learnerRow).getByRole("button", { name: "Disable" }));

    expect(await within(learnerRow).findByText("Disabled")).toBeInTheDocument();
    expect(within(learnerRow).getByRole("button", { name: "Enable" })).toBeInTheDocument();
  });

  it("shows a conflict message when an action fails", async () => {
    const user = userEvent.setup();
    queue("GET", "/api/admin/users", { status: 200, body: [ADMIN, LEARNER] });
    queue("POST", "/api/admin/users/learner-1/disable", { status: 409 });

    render(<AdminUsersPage currentUserId="admin-1" />);
    const learnerRow = (await screen.findByText("learner@example.com")).closest("tr")!;

    await user.click(within(learnerRow).getByRole("button", { name: "Disable" }));

    expect(await within(learnerRow).findByRole("alert")).toHaveTextContent(
      "This user is already disabled.",
    );
  });

  it("shows an error message when the user list fails to load", async () => {
    queue("GET", "/api/admin/users", { status: 500 });

    render(<AdminUsersPage currentUserId="admin-1" />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Could not load the user list. Please try again.",
    );
  });

  it("requires a second click to confirm erasing a user", async () => {
    const user = userEvent.setup();
    queue("GET", "/api/admin/users", { status: 200, body: [ADMIN, LEARNER] });
    queue("POST", "/api/admin/users/learner-1/erase", { status: 204 });
    queue("GET", "/api/admin/users", {
      status: 200,
      body: [ADMIN, { ...LEARNER, disabled_at: "2026-09-05T00:00:00Z", erased_at: "2026-09-05T00:00:00Z" }],
    });

    render(<AdminUsersPage currentUserId="admin-1" />);
    const learnerRow = (await screen.findByText("learner@example.com")).closest("tr")!;

    await user.click(within(learnerRow).getByRole("button", { name: "Erase" }));
    expect(within(learnerRow).queryByRole("button", { name: "Erase" })).not.toBeInTheDocument();
    await user.click(within(learnerRow).getByRole("button", { name: "Confirm erase" }));

    expect(await within(learnerRow).findByText("Erased")).toBeInTheDocument();
  });
});
