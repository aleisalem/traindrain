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
  two_factor_enabled: true,
};

describe("App two-factor login flow", () => {
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

  it("prompts for a second-factor code after a password-only login succeeds", async () => {
    const user = userEvent.setup();
    queue("GET", "/api/auth/me", { status: 401, body: {} });
    queue("POST", "/api/auth/login", {
      status: 200,
      body: { must_change_password: false, two_factor_required: true },
    });

    render(<App />);
    await screen.findByRole("heading", { name: "Sign in" });

    await user.type(screen.getByLabelText("Email"), "two-factor@example.com");
    await user.type(screen.getByLabelText("Password"), "a-perfectly-fine-passphrase");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(
      await screen.findByRole("heading", { name: "Enter your authentication code" }),
    ).toBeInTheDocument();
  });

  it("reaches the dashboard after a valid second-factor code", async () => {
    const user = userEvent.setup();
    queue("GET", "/api/auth/me", { status: 401, body: {} });
    queue("POST", "/api/auth/login", {
      status: 200,
      body: { must_change_password: false, two_factor_required: true },
    });

    render(<App />);
    await screen.findByRole("heading", { name: "Sign in" });
    await user.type(screen.getByLabelText("Email"), "two-factor@example.com");
    await user.type(screen.getByLabelText("Password"), "a-perfectly-fine-passphrase");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    await screen.findByRole("heading", { name: "Enter your authentication code" });

    queue("POST", "/api/auth/2fa/verify", {
      status: 200,
      body: { must_change_password: false, two_factor_required: false },
    });
    queue("GET", "/api/auth/me", { status: 200, body: USER_BODY });

    await user.type(
      screen.getByLabelText("Authentication or recovery code"),
      "123456",
    );
    await user.click(screen.getByRole("button", { name: "Verify" }));

    expect(await screen.findByText("Signed in as learner@example.com")).toBeInTheDocument();
  });

  it("shows an error and stays on the code prompt for an invalid code", async () => {
    const user = userEvent.setup();
    queue("GET", "/api/auth/me", { status: 401, body: {} });
    queue("POST", "/api/auth/login", {
      status: 200,
      body: { must_change_password: false, two_factor_required: true },
    });

    render(<App />);
    await screen.findByRole("heading", { name: "Sign in" });
    await user.type(screen.getByLabelText("Email"), "two-factor@example.com");
    await user.type(screen.getByLabelText("Password"), "a-perfectly-fine-passphrase");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    await screen.findByRole("heading", { name: "Enter your authentication code" });

    queue("POST", "/api/auth/2fa/verify", { status: 401, body: { detail: "Invalid code." } });

    await user.type(screen.getByLabelText("Authentication or recovery code"), "000000");
    await user.click(screen.getByRole("button", { name: "Verify" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "That code isn't valid. Please try again.",
    );
    expect(
      screen.getByRole("heading", { name: "Enter your authentication code" }),
    ).toBeInTheDocument();
  });
});
