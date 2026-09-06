import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import i18n from "./i18n";
import "./i18n";

describe("Forgot/reset-password routes", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("en");
    document.documentElement.removeAttribute("data-theme");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("/forgot-password is reachable without a session, instead of the login form", async () => {
    window.history.pushState({}, "", "/forgot-password");
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({}), { status: 401 })));

    render(<App />);

    expect(
      await screen.findByRole("heading", { name: "Reset your password" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Sign in" })).not.toBeInTheDocument();
  });

  it("/reset-password is reachable without a session, instead of the login form", async () => {
    window.history.pushState({}, "", "/reset-password?token=some-token");
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({}), { status: 401 })));

    render(<App />);

    expect(
      await screen.findByRole("heading", { name: "Choose a new password" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Sign in" })).not.toBeInTheDocument();
  });
});
