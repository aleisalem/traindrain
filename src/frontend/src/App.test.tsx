import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import App from "./App";
import "./i18n";
import i18n from "./i18n";

describe("App", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("en");
    document.documentElement.removeAttribute("data-theme");
  });

  it("renders the placeholder heading via t()", async () => {
    render(<App />);
    expect(await screen.findByText("TrainDrain is up and running")).toBeInTheDocument();
  });

  it("re-renders translated text when switching language to German", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole("button", { name: "DE" }));

    expect(await screen.findByText("TrainDrain läuft")).toBeInTheDocument();
  });

  it("applies the selected theme as a data-theme attribute on <html>", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole("button", { name: "Dark" }));

    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
  });
});
