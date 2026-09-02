import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import i18n from "./i18n";
import "./i18n";

describe("Accept-invite route", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("en");
    document.documentElement.removeAttribute("data-theme");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("is reachable without a session, instead of the login form", async () => {
    window.history.pushState({}, "", "/accept-invite?token=some-token");
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = typeof input === "string" ? input : input.toString();
        if (url === "/api/auth/me") {
          return new Response(JSON.stringify({}), { status: 401 });
        }
        if (url === "/api/invites/some-token") {
          return new Response(
            JSON.stringify({ email: "invitee@example.com", language: "en" }),
            { status: 200 },
          );
        }
        throw new Error(`No mocked response for ${url}`);
      }),
    );

    render(<App />);

    expect(
      await screen.findByText("You're setting up the account for invitee@example.com."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Sign in" })).not.toBeInTheDocument();
  });
});
