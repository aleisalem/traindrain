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

describe("App", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("en");
    document.documentElement.removeAttribute("data-theme");
    // These tests exercise the post-login dashboard, so start from an
    // already-authenticated session — the login/logout journey itself is
    // covered by App.auth.test.tsx.
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify(AUTHENTICATED_USER), { status: 200 })),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders the placeholder heading via t()", async () => {
    render(<App />);
    expect(await screen.findByText("TrainDrain is up and running")).toBeInTheDocument();
  });

  it("falls back to the OS light/dark theme for a user with no stored preference", async () => {
    render(<App />);
    await screen.findByText("TrainDrain is up and running");

    // jsdom's default matchMedia reports no match, i.e. "not dark" -> light.
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
  });

  it("applies a user's persisted theme preference on login, without any interaction", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(
          JSON.stringify({ ...AUTHENTICATED_USER, preferred_theme: "dark" }),
          { status: 200 },
        ),
      ),
    );

    render(<App />);
    await screen.findByText("TrainDrain is up and running");

    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
  });

  it("links to the profile page from the dashboard", async () => {
    render(<App />);
    await screen.findByText("TrainDrain is up and running");

    expect(screen.getByRole("link", { name: "My profile" })).toHaveAttribute(
      "href",
      "/profile",
    );
  });
});
