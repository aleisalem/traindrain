import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import i18n from "../../i18n";
import "../../i18n";
import { AcceptInvitePage } from "./AcceptInvitePage";

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

function setToken(token: string | null) {
  const search = token ? `?token=${encodeURIComponent(token)}` : "";
  window.history.pushState({}, "", `/accept-invite${search}`);
}

describe("AcceptInvitePage", () => {
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

  it("shows a clear invalid message when the invite is no longer valid", async () => {
    setToken("stale-token");
    queue("GET", "/api/invites/stale-token", { status: 410, body: { detail: "gone" } });

    render(<AcceptInvitePage />);

    expect(
      await screen.findByRole("heading", { name: "This invite is no longer valid" }),
    ).toBeInTheDocument();
  });

  it("shows an invalid message when there is no token in the URL", async () => {
    setToken(null);

    render(<AcceptInvitePage />);

    expect(
      await screen.findByRole("heading", { name: "This invite is no longer valid" }),
    ).toBeInTheDocument();
  });

  it("lets a valid invitee set a password and shows success", async () => {
    const user = userEvent.setup();
    setToken("good-token");
    queue("GET", "/api/invites/good-token", {
      status: 200,
      body: { email: "invitee@example.com", language: "en" },
    });
    queue("POST", "/api/invites/good-token/accept", { status: 204, body: {} });

    render(<AcceptInvitePage />);
    await screen.findByText("You're setting up the account for invitee@example.com.");

    await user.type(screen.getByLabelText("New password"), "a-perfectly-fine-passphrase");
    await user.type(screen.getByLabelText("Confirm password"), "a-perfectly-fine-passphrase");
    await user.click(screen.getByRole("button", { name: "Create account" }));

    expect(await screen.findByRole("heading", { name: "Account created" })).toBeInTheDocument();
  });

  it("rejects mismatched passwords before submitting", async () => {
    const user = userEvent.setup();
    setToken("good-token-2");
    queue("GET", "/api/invites/good-token-2", {
      status: 200,
      body: { email: "invitee2@example.com", language: "en" },
    });

    render(<AcceptInvitePage />);
    await screen.findByText("You're setting up the account for invitee2@example.com.");

    await user.type(screen.getByLabelText("New password"), "a-perfectly-fine-passphrase");
    await user.type(screen.getByLabelText("Confirm password"), "does-not-match");
    await user.click(screen.getByRole("button", { name: "Create account" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Passwords don't match.");
  });

  it("shows a policy-violation message for a weak password", async () => {
    const user = userEvent.setup();
    setToken("good-token-3");
    queue("GET", "/api/invites/good-token-3", {
      status: 200,
      body: { email: "invitee3@example.com", language: "en" },
    });
    queue("POST", "/api/invites/good-token-3/accept", {
      status: 422,
      body: { detail: { reasons: ["too short"] } },
    });

    render(<AcceptInvitePage />);
    await screen.findByText("You're setting up the account for invitee3@example.com.");

    await user.type(screen.getByLabelText("New password"), "short");
    await user.type(screen.getByLabelText("Confirm password"), "short");
    await user.click(screen.getByRole("button", { name: "Create account" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "That password isn't allowed",
    );
  });
});
