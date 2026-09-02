import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import i18n from "../../i18n";
import "../../i18n";
import { ResetPasswordPage } from "./ResetPasswordPage";

function setToken(token: string | null) {
  const search = token ? `?token=${encodeURIComponent(token)}` : "";
  window.history.pushState({}, "", `/reset-password${search}`);
}

describe("ResetPasswordPage", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("en");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("lets a user with a valid token set a new password", async () => {
    const user = userEvent.setup();
    setToken("good-token");
    const fetchMock = vi.fn(async () => new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    render(<ResetPasswordPage />);
    await user.type(screen.getByLabelText("New password"), "a-perfectly-fine-passphrase");
    await user.type(screen.getByLabelText("Confirm password"), "a-perfectly-fine-passphrase");
    await user.click(screen.getByRole("button", { name: "Set new password" }));

    expect(await screen.findByRole("heading", { name: "Password updated" })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/auth/reset-password",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ token: "good-token", password: "a-perfectly-fine-passphrase" }),
      }),
    );
  });

  it("rejects mismatched passwords before submitting", async () => {
    const user = userEvent.setup();
    setToken("good-token-2");
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new Error("should not be called");
      }),
    );

    render(<ResetPasswordPage />);
    await user.type(screen.getByLabelText("New password"), "a-perfectly-fine-passphrase");
    await user.type(screen.getByLabelText("Confirm password"), "does-not-match");
    await user.click(screen.getByRole("button", { name: "Set new password" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Passwords don't match.");
  });

  it("shows an invalid-link message for an expired or used token", async () => {
    const user = userEvent.setup();
    setToken("stale-token");
    vi.stubGlobal("fetch", vi.fn(async () => new Response(null, { status: 410 })));

    render(<ResetPasswordPage />);
    await user.type(screen.getByLabelText("New password"), "a-perfectly-fine-passphrase");
    await user.type(screen.getByLabelText("Confirm password"), "a-perfectly-fine-passphrase");
    await user.click(screen.getByRole("button", { name: "Set new password" }));

    expect(
      await screen.findByRole("heading", { name: "This reset link is no longer valid" }),
    ).toBeInTheDocument();
  });

  it("shows a policy-violation message for a weak password", async () => {
    const user = userEvent.setup();
    setToken("good-token-3");
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ detail: { reasons: ["too short"] } }), {
        status: 422,
        headers: { "Content-Type": "application/json" },
      })),
    );

    render(<ResetPasswordPage />);
    await user.type(screen.getByLabelText("New password"), "short");
    await user.type(screen.getByLabelText("Confirm password"), "short");
    await user.click(screen.getByRole("button", { name: "Set new password" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("That password isn't allowed");
  });

  it("shows an invalid-link message when there is no token in the URL", async () => {
    const user = userEvent.setup();
    setToken(null);
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new Error("should not be called");
      }),
    );

    render(<ResetPasswordPage />);
    await user.type(screen.getByLabelText("New password"), "a-perfectly-fine-passphrase");
    await user.type(screen.getByLabelText("Confirm password"), "a-perfectly-fine-passphrase");
    await user.click(screen.getByRole("button", { name: "Set new password" }));

    expect(
      await screen.findByRole("heading", { name: "This reset link is no longer valid" }),
    ).toBeInTheDocument();
  });
});
