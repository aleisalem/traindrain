import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import i18n from "./i18n";
import "./i18n";

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
    // Fetch forbids a body on null-body statuses (204/205/304).
    const hasBody = ![204, 205, 304].includes(queued.status);
    return new Response(hasBody ? JSON.stringify(queued.body) : null, {
      status: queued.status,
      headers: hasBody ? { "Content-Type": "application/json" } : {},
    });
  });

  return { fetchMock, queue };
}

const USER_BODY = {
  id: "11111111-1111-1111-1111-111111111111",
  email: "learner@example.com",
  first_name: "Ada",
  last_name: "Lovelace",
  must_change_password: false,
  roles: ["Learner"],
};

describe("App auth flow", () => {
  let queue: ReturnType<typeof createFetchMock>["queue"];

  beforeEach(async () => {
    await i18n.changeLanguage("en");
    document.documentElement.removeAttribute("data-theme");
    const mock = createFetchMock();
    queue = mock.queue;
    vi.stubGlobal("fetch", mock.fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows the login form when there is no session", async () => {
    queue("GET", "/api/auth/me", { status: 401, body: {} });

    render(<App />);

    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  });

  it("shows the dashboard directly for a session that doesn't need a password change", async () => {
    queue("GET", "/api/auth/me", { status: 200, body: USER_BODY });

    render(<App />);

    expect(await screen.findByText("Signed in as learner@example.com")).toBeInTheDocument();
  });

  it("shows a generic error for invalid credentials", async () => {
    const user = userEvent.setup();
    queue("GET", "/api/auth/me", { status: 401, body: {} });
    queue("POST", "/api/auth/login", { status: 401, body: { detail: "Invalid email or password." } });

    render(<App />);
    await screen.findByRole("heading", { name: "Sign in" });

    await user.type(screen.getByLabelText("Email"), "someone@example.com");
    await user.type(screen.getByLabelText("Password"), "wrong-password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid email or password.");
  });

  it("shows a rate-limit error after too many attempts", async () => {
    const user = userEvent.setup();
    queue("GET", "/api/auth/me", { status: 401, body: {} });
    queue("POST", "/api/auth/login", { status: 429, body: { detail: "Too many login attempts." } });

    render(<App />);
    await screen.findByRole("heading", { name: "Sign in" });

    await user.type(screen.getByLabelText("Email"), "someone@example.com");
    await user.type(screen.getByLabelText("Password"), "whatever");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Too many attempts. Please wait a few minutes and try again.",
    );
  });

  it("walks a forced first-login password change through to the dashboard", async () => {
    const user = userEvent.setup();
    queue("GET", "/api/auth/me", { status: 401, body: {} });
    queue("POST", "/api/auth/login", { status: 200, body: { must_change_password: true } });
    queue("GET", "/api/auth/me", {
      status: 403,
      body: { detail: { code: "password_change_required" } },
    });

    render(<App />);
    await screen.findByRole("heading", { name: "Sign in" });

    await user.type(screen.getByLabelText("Email"), "admin@example.com");
    await user.type(screen.getByLabelText("Password"), "one-time-random-password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(
      await screen.findByRole("heading", { name: "Set a new password" }),
    ).toBeInTheDocument();

    queue("POST", "/api/auth/change-password", {
      status: 200,
      body: { must_change_password: false },
    });
    queue("GET", "/api/auth/me", { status: 200, body: USER_BODY });

    await user.type(screen.getByLabelText("Current password"), "one-time-random-password");
    await user.type(screen.getByLabelText("New password"), "a-brand-new-passphrase");
    await user.click(screen.getByRole("button", { name: "Set new password" }));

    expect(await screen.findByText("Signed in as learner@example.com")).toBeInTheDocument();
  });

  it("shows an error when the current password is wrong", async () => {
    const user = userEvent.setup();
    queue("GET", "/api/auth/me", {
      status: 403,
      body: { detail: { code: "password_change_required" } },
    });
    queue("POST", "/api/auth/change-password", {
      status: 401,
      body: { detail: "Current password is incorrect." },
    });

    render(<App />);
    await screen.findByRole("heading", { name: "Set a new password" });

    await user.type(screen.getByLabelText("Current password"), "not-the-password");
    await user.type(screen.getByLabelText("New password"), "a-brand-new-passphrase");
    await user.click(screen.getByRole("button", { name: "Set new password" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Current password is incorrect.");
  });

  it("logs out back to the login form", async () => {
    const user = userEvent.setup();
    queue("GET", "/api/auth/me", { status: 200, body: USER_BODY });
    queue("POST", "/api/auth/logout", { status: 204, body: {} });

    render(<App />);
    await screen.findByText("Signed in as learner@example.com");

    await user.click(screen.getByRole("button", { name: "Log out" }));

    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  });
});
