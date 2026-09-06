import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import i18n from "./i18n";
import "./i18n";

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

function mockBackend(user: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url === "/api/auth/me") {
        return new Response(JSON.stringify(user), { status: 200 });
      }
      if (url === "/api/admin/ping") {
        return new Response(JSON.stringify({ status: "ok" }), { status: 200 });
      }
      if (url === "/api/admin/roles") {
        return new Response(JSON.stringify([{ id: "role-learner", name: "Learner" }]), {
          status: 200,
        });
      }
      if (url === "/api/admin/groups") {
        return new Response(JSON.stringify([]), { status: 200 });
      }
      if (url === "/api/admin/users") {
        return new Response(JSON.stringify([]), { status: 200 });
      }
      if (url === "/api/admin/settings/invite-expiry-days") {
        return new Response(JSON.stringify({ days: 7 }), { status: 200 });
      }
      throw new Error(`No mocked response for ${url}`);
    }),
  );
}

describe("Admin shell routing", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("en");
    document.documentElement.removeAttribute("data-theme");
    window.history.pushState({}, "", "/");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows the admin nav link and lets an Administrator reach the admin area", async () => {
    const user = userEvent.setup();
    mockBackend(ADMIN_USER);

    render(<App />);
    await screen.findByText("Signed in as admin@example.com");

    await user.click(screen.getByRole("link", { name: "Admin area" }));

    expect(await screen.findByRole("heading", { name: "Overview" })).toBeInTheDocument();
  });

  it("lets an Administrator navigate to the invite-user page", async () => {
    const user = userEvent.setup();
    mockBackend(ADMIN_USER);

    render(<App />);
    await screen.findByText("Signed in as admin@example.com");

    await user.click(screen.getByRole("link", { name: "Admin area" }));
    await screen.findByRole("heading", { name: "Overview" });
    await user.click(screen.getByRole("link", { name: "Invite user" }));

    expect(await screen.findByRole("heading", { name: "Invite a user" })).toBeInTheDocument();
  });

  it("lets an Administrator navigate to the groups page", async () => {
    const user = userEvent.setup();
    mockBackend(ADMIN_USER);

    render(<App />);
    await screen.findByText("Signed in as admin@example.com");

    await user.click(screen.getByRole("link", { name: "Admin area" }));
    await screen.findByRole("heading", { name: "Overview" });
    await user.click(screen.getByRole("link", { name: "Manage groups" }));

    expect(await screen.findByRole("heading", { name: "Groups" })).toBeInTheDocument();
  });

  it("hides the admin nav link for a Learner", async () => {
    mockBackend(LEARNER_USER);

    render(<App />);
    await screen.findByText("Signed in as learner@example.com");

    expect(screen.queryByRole("link", { name: "Admin area" })).not.toBeInTheDocument();
  });

  it("redirects a Learner who navigates directly to /admin back to the dashboard", async () => {
    window.history.pushState({}, "", "/admin");
    mockBackend(LEARNER_USER);

    render(<App />);

    expect(await screen.findByText("Signed in as learner@example.com")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Overview" })).not.toBeInTheDocument();
  });
});
