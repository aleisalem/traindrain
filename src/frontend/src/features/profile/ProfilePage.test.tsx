import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import i18n from "../../i18n";
import "../../i18n";
import type { AuthUser } from "../auth/useAuth";
import { ProfilePage } from "./ProfilePage";

type Props = ComponentProps<typeof ProfilePage>;

const USER: AuthUser = {
  id: "11111111-1111-1111-1111-111111111111",
  email: "learner@example.com",
  firstName: "Ada",
  lastName: "Lovelace",
  mustChangePassword: false,
  roles: ["Learner"],
  twoFactorEnabled: false,
  preferredLanguage: null,
  preferredTheme: null,
};

type RenderOptions = {
  user?: AuthUser;
  onUpdateName?: Props["onUpdateName"];
  onUpdatePreferences?: Props["onUpdatePreferences"];
  onChangePassword?: Props["onChangePassword"];
};

function renderProfilePage(options: RenderOptions = {}) {
  const onUpdateName = options.onUpdateName ?? vi.fn();
  const onUpdatePreferences = options.onUpdatePreferences ?? vi.fn();
  const onChangePassword = options.onChangePassword ?? vi.fn();

  render(
    <MemoryRouter>
      <ProfilePage
        user={options.user ?? USER}
        onUpdateName={onUpdateName}
        onUpdatePreferences={onUpdatePreferences}
        onChangePassword={onChangePassword}
      />
    </MemoryRouter>,
  );

  return { onUpdateName, onUpdatePreferences, onChangePassword };
}

describe("ProfilePage", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("en");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows the current name and email", () => {
    renderProfilePage();

    expect(screen.getByText("learner@example.com")).toBeInTheDocument();
    expect(screen.getByLabelText("First name")).toHaveValue("Ada");
    expect(screen.getByLabelText("Last name")).toHaveValue("Lovelace");
  });

  it("submits an updated name and shows confirmation", async () => {
    const user = userEvent.setup();
    const { onUpdateName } = renderProfilePage({
      onUpdateName: vi.fn().mockResolvedValue({ ok: true }),
    });

    await user.clear(screen.getByLabelText("First name"));
    await user.type(screen.getByLabelText("First name"), "Grace");
    await user.clear(screen.getByLabelText("Last name"));
    await user.type(screen.getByLabelText("Last name"), "Hopper");
    await user.click(screen.getByRole("button", { name: "Save name" }));

    expect(onUpdateName).toHaveBeenCalledWith("Grace", "Hopper");
    expect(await screen.findByText("Name updated.")).toBeInTheDocument();
  });

  it("shows an error when the name update is rejected", async () => {
    const user = userEvent.setup();
    renderProfilePage({
      onUpdateName: vi.fn().mockResolvedValue({ ok: false, error: "invalid" }),
    });

    await user.click(screen.getByRole("button", { name: "Save name" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "First and last name can't be blank.",
    );
  });

  it("submits a password change and shows confirmation", async () => {
    const user = userEvent.setup();
    const { onChangePassword } = renderProfilePage({
      onChangePassword: vi.fn().mockResolvedValue({ ok: true }),
    });

    await user.type(screen.getByLabelText("Current password"), "old-passphrase-1");
    await user.type(screen.getByLabelText("New password"), "new-passphrase-2");
    await user.click(screen.getByRole("button", { name: "Change password" }));

    expect(onChangePassword).toHaveBeenCalledWith("old-passphrase-1", "new-passphrase-2");
    expect(await screen.findByText("Password updated.")).toBeInTheDocument();
    expect(screen.getByLabelText("Current password")).toHaveValue("");
  });

  it("shows an error when the current password is wrong", async () => {
    const user = userEvent.setup();
    renderProfilePage({
      onChangePassword: vi.fn().mockResolvedValue({ ok: false, error: "wrong_current_password" }),
    });

    await user.type(screen.getByLabelText("Current password"), "wrong-passphrase");
    await user.type(screen.getByLabelText("New password"), "new-passphrase-2");
    await user.click(screen.getByRole("button", { name: "Change password" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Current password is incorrect.",
    );
  });

  it("persists a language selection", async () => {
    const user = userEvent.setup();
    const { onUpdatePreferences } = renderProfilePage({
      onUpdatePreferences: vi.fn().mockResolvedValue({ ok: true }),
    });

    await user.click(screen.getByRole("button", { name: "DE" }));

    // No stored theme preference yet -> the OS-default fallback (light in
    // jsdom) is sent alongside the newly-picked language.
    expect(onUpdatePreferences).toHaveBeenCalledWith("de", "light");
  });

  it("persists a theme selection", async () => {
    const user = userEvent.setup();
    const { onUpdatePreferences } = renderProfilePage({
      onUpdatePreferences: vi.fn().mockResolvedValue({ ok: true }),
    });

    await user.click(screen.getByRole("button", { name: "Dark" }));

    expect(onUpdatePreferences).toHaveBeenCalledWith("en", "dark");
  });

  it("marks the user's stored preferences as the pressed option", () => {
    renderProfilePage({
      user: { ...USER, preferredLanguage: "de", preferredTheme: "colorblind" },
    });

    expect(screen.getByRole("button", { name: "DE" })).toHaveAttribute("aria-pressed", "true");
    expect(
      screen.getByRole("button", { name: "Colorblind-friendly" }),
    ).toHaveAttribute("aria-pressed", "true");
  });
});
