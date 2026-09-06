import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import i18n from "../../i18n";
import "../../i18n";
import { ForgotPasswordPage } from "./ForgotPasswordPage";

describe("ForgotPasswordPage", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("en");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows the same generic confirmation regardless of whether the email exists", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn(async () => new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    render(<ForgotPasswordPage />);
    await user.type(screen.getByLabelText("Email"), "someone@example.com");
    await user.click(screen.getByRole("button", { name: "Send reset link" }));

    expect(await screen.findByRole("heading", { name: "Check your email" })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/auth/forgot-password",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ email: "someone@example.com" }),
      }),
    );
  });

  it("shows the same confirmation even if the request fails outright", async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new Error("network error");
      }),
    );

    render(<ForgotPasswordPage />);
    await user.type(screen.getByLabelText("Email"), "someone@example.com");
    await user.click(screen.getByRole("button", { name: "Send reset link" }));

    expect(await screen.findByRole("heading", { name: "Check your email" })).toBeInTheDocument();
  });
});
