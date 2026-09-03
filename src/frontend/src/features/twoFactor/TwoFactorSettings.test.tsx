import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import i18n from "../../i18n";
import "../../i18n";
import { TwoFactorSettings } from "./TwoFactorSettings";

type MockResponse = { status: number; body: unknown };

function createFetchMock() {
  const queues = new Map<string, MockResponse[]>();

  function queue(method: string, url: string, response: MockResponse) {
    const key = `${method} ${url}`;
    const existing = queues.get(key) ?? [];
    existing.push(response);
    queues.set(key, existing);
  }

  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    const method = init?.method ?? "GET";
    const key = `${method} ${url}`;
    const queued = queues.get(key)?.shift();
    if (!queued) throw new Error(`No mocked response queued for ${key}`);
    const hasBody = ![204, 205, 304].includes(queued.status);
    return new Response(hasBody ? JSON.stringify(queued.body) : null, {
      status: queued.status,
      headers: hasBody ? { "Content-Type": "application/json" } : {},
    });
  });

  return { fetchMock, queue };
}

describe("TwoFactorSettings", () => {
  let queue: ReturnType<typeof createFetchMock>["queue"];

  beforeEach(async () => {
    await i18n.changeLanguage("en");
    const mock = createFetchMock();
    queue = mock.queue;
    vi.stubGlobal("fetch", mock.fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows an enabled status and no enroll button once enabled", () => {
    render(<TwoFactorSettings enabled={true} onChanged={vi.fn()} />);

    expect(
      screen.getByText("Two-factor authentication is enabled on your account."),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Enable two-factor authentication" }),
    ).not.toBeInTheDocument();
  });

  it("walks enrollment through to showing recovery codes once", async () => {
    const user = userEvent.setup();
    const onChanged = vi.fn();
    queue("POST", "/api/auth/2fa/enroll", {
      status: 200,
      body: { secret: "JBSWY3DPEHPK3PXP", qr_code_data_uri: "data:image/png;base64,AAA" },
    });

    render(<TwoFactorSettings enabled={false} onChanged={onChanged} />);

    await user.click(screen.getByRole("button", { name: "Enable two-factor authentication" }));

    expect(await screen.findByRole("heading", { name: "Scan the QR code" })).toBeInTheDocument();
    expect(screen.getByText("JBSWY3DPEHPK3PXP")).toBeInTheDocument();

    queue("POST", "/api/auth/2fa/enable", {
      status: 200,
      body: {
        recovery_codes: [
          "AAAAA-11111",
          "BBBBB-22222",
          "CCCCC-33333",
          "DDDDD-44444",
          "EEEEE-55555",
          "FFFFF-66666",
          "GGGGG-77777",
          "HHHHH-88888",
          "IIIII-99999",
          "JJJJJ-00000",
        ],
      },
    });

    await user.type(screen.getByLabelText("Authentication or recovery code"), "123456");
    await user.click(screen.getByRole("button", { name: "Confirm and enable" }));

    expect(
      await screen.findByRole("heading", { name: "Save your recovery codes" }),
    ).toBeInTheDocument();
    expect(screen.getByText("AAAAA-11111")).toBeInTheDocument();
    expect(screen.getByText("JJJJJ-00000")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "I've saved these codes" }));

    expect(onChanged).toHaveBeenCalledTimes(1);
  });

  it("shows an error and stays on the confirmation step for an invalid code", async () => {
    const user = userEvent.setup();
    queue("POST", "/api/auth/2fa/enroll", {
      status: 200,
      body: { secret: "JBSWY3DPEHPK3PXP", qr_code_data_uri: "data:image/png;base64,AAA" },
    });

    render(<TwoFactorSettings enabled={false} onChanged={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: "Enable two-factor authentication" }));
    await screen.findByRole("heading", { name: "Scan the QR code" });

    queue("POST", "/api/auth/2fa/enable", { status: 401, body: { detail: "Invalid code." } });

    await user.type(screen.getByLabelText("Authentication or recovery code"), "000000");
    await user.click(screen.getByRole("button", { name: "Confirm and enable" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "That code isn't valid. Please try again.",
    );
    expect(screen.getByRole("heading", { name: "Scan the QR code" })).toBeInTheDocument();
  });

  it("disables two-factor authentication after confirming with the current password", async () => {
    const user = userEvent.setup();
    const onChanged = vi.fn();
    queue("POST", "/api/auth/2fa/disable", { status: 204, body: undefined });

    render(<TwoFactorSettings enabled={true} onChanged={onChanged} />);

    await user.click(screen.getByRole("button", { name: "Disable two-factor authentication" }));
    await user.type(screen.getByLabelText("Password"), "correct-password");
    await user.click(screen.getByRole("button", { name: "Disable" }));

    await vi.waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));

    const call = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.find(
      (args: unknown[]) => args[0] === "/api/auth/2fa/disable",
    ) as [RequestInfo, RequestInit];
    expect(JSON.parse(call[1].body as string)).toEqual({ password: "correct-password" });
  });

  it("shows an error and stays enabled when the disable password is wrong", async () => {
    const user = userEvent.setup();
    const onChanged = vi.fn();
    queue("POST", "/api/auth/2fa/disable", { status: 401, body: { detail: "Incorrect password." } });

    render(<TwoFactorSettings enabled={true} onChanged={onChanged} />);

    await user.click(screen.getByRole("button", { name: "Disable two-factor authentication" }));
    await user.type(screen.getByLabelText("Password"), "wrong-password");
    await user.click(screen.getByRole("button", { name: "Disable" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Current password is incorrect.");
    expect(onChanged).not.toHaveBeenCalled();
    expect(screen.getByText("Two-factor authentication is enabled on your account.")).toBeInTheDocument();
  });

  it("lets the user cancel out of the disable confirmation", async () => {
    const user = userEvent.setup();

    render(<TwoFactorSettings enabled={true} onChanged={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: "Disable two-factor authentication" }));
    expect(screen.getByLabelText("Password")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.queryByLabelText("Password")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Disable two-factor authentication" }),
    ).toBeInTheDocument();
  });
});
