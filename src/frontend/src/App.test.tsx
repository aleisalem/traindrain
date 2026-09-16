import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import "./i18n";
import i18n from "./i18n";

const AUTHENTICATED_USER = {
  id: "11111111-1111-1111-1111-111111111111",
  email: "learner@example.com",
  first_name: "Ada",
  last_name: "Lovelace",
  must_change_password: false,
  roles: ["Learner"],
};

function mockBackend(user: unknown = AUTHENTICATED_USER) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url === "/api/auth/me") return new Response(JSON.stringify(user), { status: 200 });
      if (url === "/api/me/modules") return new Response(JSON.stringify([]), { status: 200 });
      throw new Error(`No mocked response for ${url}`);
    }),
  );
}

describe("App", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("en");
    document.documentElement.removeAttribute("data-theme");
    window.history.pushState({}, "", "/");
    // These tests exercise the post-login landing page, so start from an
    // already-authenticated session — the login/logout journey itself is
    // covered by App.auth.test.tsx.
    mockBackend();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("lands a Learner on My Learning, not a shared placeholder", async () => {
    render(<App />);
    expect(await screen.findByRole("heading", { name: "My learning" })).toBeInTheDocument();
  });

  it("does not show a backend health-check on the landing page", async () => {
    render(<App />);
    await screen.findByRole("heading", { name: "My learning" });

    expect(screen.queryByText(/backend/i)).not.toBeInTheDocument();
  });

  it("falls back to the OS light/dark theme for a user with no stored preference", async () => {
    render(<App />);
    await screen.findByRole("heading", { name: "My learning" });

    // jsdom's default matchMedia reports no match, i.e. "not dark" -> light.
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
  });

  it("applies a user's persisted theme preference on login, without any interaction", async () => {
    mockBackend({ ...AUTHENTICATED_USER, preferred_theme: "dark" });

    render(<App />);
    await screen.findByRole("heading", { name: "My learning" });

    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
  });

  it("links the profile control to the preferences page", async () => {
    render(<App />);
    await screen.findByRole("heading", { name: "My learning" });

    expect(screen.getByRole("link", { name: /Preferences/ })).toHaveAttribute("href", "/profile");
  });
});
