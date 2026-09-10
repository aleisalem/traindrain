import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import i18n from "./i18n";
import "./i18n";

const LEARNER_USER = {
  id: "11111111-1111-1111-1111-111111111111",
  email: "learner@example.com",
  first_name: "Grace",
  last_name: "Hopper",
  must_change_password: false,
  roles: ["Learner"],
};

const CATALOG_ENTRY = {
  translation_group_id: "group-1",
  language: "en",
  title: "Phishing Awareness",
  description: "How to spot a phish.",
  estimated_duration_minutes: 15,
  page_count: 2,
  started: false,
  completed_at: null,
};

function mockBackend(routes: Record<string, unknown>) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url === "/api/auth/me") {
        return new Response(JSON.stringify(LEARNER_USER), { status: 200 });
      }
      if (url in routes) return new Response(JSON.stringify(routes[url]), { status: 200 });
      throw new Error(`No mocked response for ${url}`);
    }),
  );
}

describe("Learner area routing", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("en");
    document.documentElement.removeAttribute("data-theme");
    window.history.pushState({}, "", "/");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("lets a Learner reach their own material from the dashboard and browse the catalog", async () => {
    const user = userEvent.setup();
    mockBackend({ "/api/me/modules": [], "/api/catalog/modules": [CATALOG_ENTRY] });

    render(<App />);
    await screen.findByText("Signed in as learner@example.com");

    // Reading is not a privilege: no role gates this, unlike /admin and /content.
    await user.click(screen.getByRole("link", { name: "My learning" }));
    expect(await screen.findByText("You haven't opened anything yet.")).toBeInTheDocument();

    await user.click(screen.getByRole("link", { name: "Browse catalog" }));

    expect(await screen.findByText("Phishing Awareness")).toBeInTheDocument();
  });
});
