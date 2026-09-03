import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import i18n from "../../i18n";
import "../../i18n";
import { AdminDisableTwoFactorPage } from "./AdminDisableTwoFactorPage";

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
    const hasBody = queued.body !== undefined && ![204, 205, 304].includes(queued.status);
    return new Response(hasBody ? JSON.stringify(queued.body) : null, {
      status: queued.status,
      headers: hasBody ? { "Content-Type": "application/json" } : {},
    });
  });

  return { fetchMock, queue };
}

describe("AdminDisableTwoFactorPage", () => {
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

  it("submits the target's email and shows a success message", async () => {
    const user = userEvent.setup();
    queue("POST", "/api/admin/users/2fa/disable", { status: 204 });

    render(<AdminDisableTwoFactorPage />);

    await user.type(screen.getByLabelText("User's email"), "locked-out@example.com");
    await user.click(screen.getByRole("button", { name: "Disable 2FA for this user" }));

    expect(
      await screen.findByText("Two-factor authentication has been disabled for locked-out@example.com."),
    ).toBeInTheDocument();

    const call = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.find(
      (args: unknown[]) => args[0] === "/api/admin/users/2fa/disable",
    ) as [RequestInfo, RequestInit];
    expect(JSON.parse(call[1].body as string)).toEqual({ email: "locked-out@example.com" });
  });

  it("shows a not-found message for an unknown email", async () => {
    const user = userEvent.setup();
    queue("POST", "/api/admin/users/2fa/disable", { status: 404, body: { detail: "not found" } });

    render(<AdminDisableTwoFactorPage />);

    await user.type(screen.getByLabelText("User's email"), "nobody@example.com");
    await user.click(screen.getByRole("button", { name: "Disable 2FA for this user" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "No user found with that email.",
    );
  });

  it("shows a not-enabled message when the target has no 2FA to disable", async () => {
    const user = userEvent.setup();
    queue("POST", "/api/admin/users/2fa/disable", { status: 409, body: { detail: "conflict" } });

    render(<AdminDisableTwoFactorPage />);

    await user.type(screen.getByLabelText("User's email"), "never-enrolled@example.com");
    await user.click(screen.getByRole("button", { name: "Disable 2FA for this user" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Two-factor authentication isn't enabled for this user.",
    );
  });
});
