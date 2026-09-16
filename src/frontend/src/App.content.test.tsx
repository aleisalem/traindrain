import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import i18n from "./i18n";
import "./i18n";

const CONTENT_MANAGER_USER = {
  id: "33333333-3333-3333-3333-333333333333",
  email: "author@example.com",
  first_name: "Cora",
  last_name: "Manager",
  must_change_password: false,
  roles: ["Content Manager"],
};

const ADMIN_USER = {
  id: "22222222-2222-2222-2222-222222222222",
  email: "admin@example.com",
  first_name: "Ada",
  last_name: "Lovelace",
  must_change_password: false,
  roles: ["Administrator"],
};

const LEARNER_USER = {
  id: "11111111-1111-1111-1111-111111111111",
  email: "learner@example.com",
  first_name: "Grace",
  last_name: "Hopper",
  must_change_password: false,
  roles: ["Learner"],
};

const MODULE = {
  id: "module-1",
  translation_group_id: "group-1",
  language: "en",
  title: "Phishing Awareness",
  description: "How to spot a phish.",
  estimated_duration_minutes: 15,
  status: "draft",
  current_version_number: null,
  created_by: { id: CONTENT_MANAGER_USER.id, display_name: "Cora Manager" },
  last_edited_by: { id: CONTENT_MANAGER_USER.id, display_name: "Cora Manager" },
  created_at: "2026-09-01T00:00:00Z",
  updated_at: "2026-09-01T00:00:00Z",
};

function mockBackend(user: unknown, modules: unknown[] = [MODULE]) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url === "/api/auth/me") return new Response(JSON.stringify(user), { status: 200 });
      if (url === "/api/content/modules") {
        return new Response(JSON.stringify(modules), { status: 200 });
      }
      if (url === "/api/me/modules") {
        return new Response(JSON.stringify([]), { status: 200 });
      }
      throw new Error(`No mocked response for ${url}`);
    }),
  );
}

describe("Content area routing", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("en");
    document.documentElement.removeAttribute("data-theme");
    window.history.pushState({}, "", "/");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("lands a Content Manager on the content area directly", async () => {
    mockBackend(CONTENT_MANAGER_USER);

    render(<App />);

    expect(
      await screen.findByRole("heading", { name: "Learning modules" }),
    ).toBeInTheDocument();
    expect(await screen.findByText("Phishing Awareness")).toBeInTheDocument();
  });

  it("lets an Administrator reach the content area too", async () => {
    const user = userEvent.setup();
    mockBackend(ADMIN_USER);

    render(<App />);
    await screen.findByRole("heading", { name: "Overview" });

    await user.click(screen.getByRole("link", { name: "Modules" }));

    expect(
      await screen.findByRole("heading", { name: "Learning modules" }),
    ).toBeInTheDocument();
  });

  it("hides the content-area nav group from a Learner", async () => {
    mockBackend(LEARNER_USER);

    render(<App />);
    await screen.findByRole("heading", { name: "My learning" });

    expect(screen.queryByText("Content area")).not.toBeInTheDocument();
  });

  it("redirects a Learner who navigates straight to /content back to their own landing page", async () => {
    window.history.pushState({}, "", "/content");
    mockBackend(LEARNER_USER);

    render(<App />);

    expect(await screen.findByRole("heading", { name: "My learning" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Learning modules" })).not.toBeInTheDocument();
  });

  it("redirects a Learner who navigates straight to a module's edit URL", async () => {
    window.history.pushState({}, "", "/content/module-1");
    mockBackend(LEARNER_USER);

    render(<App />);

    expect(await screen.findByRole("heading", { name: "My learning" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Module details" })).not.toBeInTheDocument();
  });

  it("does not open the content area for a Learner even without the nav link", async () => {
    mockBackend(LEARNER_USER);

    render(<App />);
    await screen.findByRole("heading", { name: "My learning" });

    // The Learner's landing page never fetched the authoring API at all —
    // the route isn't mounted, so nothing behind it renders.
    const fetchMock = globalThis.fetch as unknown as ReturnType<typeof vi.fn>;
    const requested = fetchMock.mock.calls.map((call) => String(call[0]));
    expect(requested).not.toContain("/api/content/modules");
  });
});
