import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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

  it("re-renders translated text when switching language to German", async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByText("TrainDrain is up and running");

    await user.click(screen.getByRole("button", { name: "DE" }));

    expect(await screen.findByText("TrainDrain läuft")).toBeInTheDocument();
  });

  it("applies the selected theme as a data-theme attribute on <html>", async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByText("TrainDrain is up and running");

    await user.click(screen.getByRole("button", { name: "Dark" }));

    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
  });
});
