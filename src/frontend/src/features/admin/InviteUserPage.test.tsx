import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import i18n from "../../i18n";
import "../../i18n";
import { InviteUserPage } from "./InviteUserPage";

type MockResponse = { status: number; body: unknown };

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

describe("InviteUserPage", () => {
  let queue: ReturnType<typeof createFetchMock>["queue"];

  beforeEach(async () => {
    await i18n.changeLanguage("en");
    const mock = createFetchMock();
    queue = mock.queue;
    vi.stubGlobal("fetch", mock.fetchMock);
    // Fetched unconditionally on mount by the invite-expiry control.
    queue("GET", "/api/admin/settings/invite-expiry-days", { status: 200, body: { days: 7 } });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("lists every role except Learner, which is always auto-assigned", async () => {
    queue("GET", "/api/admin/roles", { status: 200, body: ROLES });

    render(<InviteUserPage />);

    expect(await screen.findByLabelText("Administrator")).toBeInTheDocument();
    expect(await screen.findByLabelText("Content Manager")).toBeInTheDocument();
    expect(screen.queryByLabelText("Learner")).not.toBeInTheDocument();
  });

  it("submits the invite with the selected email, language, and roles", async () => {
    const user = userEvent.setup();
    queue("GET", "/api/admin/roles", { status: 200, body: ROLES });
    queue("POST", "/api/admin/invites", {
      status: 201,
      body: { id: "invite-1", email: "newbie@example.com", language: "de", expires_at: "2026-09-09T00:00:00Z", roles: ["Content Manager"] },
    });

    render(<InviteUserPage />);
    await screen.findByLabelText("Content Manager");

    await user.type(screen.getByLabelText("Email"), "newbie@example.com");
    await user.selectOptions(screen.getByLabelText("Invite language"), "German");
    await user.click(screen.getByLabelText("Content Manager"));
    await user.click(screen.getByRole("button", { name: "Send invite" }));

    expect(await screen.findByText("Invite sent to newbie@example.com.")).toBeInTheDocument();

    const call = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.find(
      (args: unknown[]) => args[0] === "/api/admin/invites",
    ) as [RequestInfo, RequestInit];
    const requestInit = call[1];
    expect(JSON.parse(requestInit.body as string)).toEqual({
      email: "newbie@example.com",
      language: "de",
      role_ids: ["role-content"],
    });
  });

  it("shows a conflict message when the email already has an account", async () => {
    const user = userEvent.setup();
    queue("GET", "/api/admin/roles", { status: 200, body: ROLES });
    queue("POST", "/api/admin/invites", { status: 409, body: { detail: "conflict" } });

    render(<InviteUserPage />);
    await screen.findByLabelText("Content Manager");

    await user.type(screen.getByLabelText("Email"), "existing@example.com");
    await user.click(screen.getByRole("button", { name: "Send invite" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "A user with this email already exists.",
    );
  });

  it("lets an admin view and update the invite-link expiry", async () => {
    const user = userEvent.setup();
    queue("GET", "/api/admin/roles", { status: 200, body: ROLES });
    queue("PUT", "/api/admin/settings/invite-expiry-days", { status: 200, body: { days: 3 } });

    render(<InviteUserPage />);

    const daysInput = await screen.findByLabelText("Days until an invite link expires");
    expect(daysInput).toHaveValue(7);

    await user.clear(daysInput);
    await user.type(daysInput, "3");
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText("Saved.")).toBeInTheDocument();
    const call = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.find(
      (args: unknown[]) =>
        args[0] === "/api/admin/settings/invite-expiry-days" &&
        (args[1] as RequestInit | undefined)?.method === "PUT",
    ) as [RequestInfo, RequestInit];
    expect(JSON.parse(call[1].body as string)).toEqual({ days: 3 });
  });
});
