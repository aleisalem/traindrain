import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import i18n from "../../i18n";
import "../../i18n";
import { initials, ModuleEditorsPresence } from "./ModuleEditorsPresence";
import { ModuleFormPage } from "./ModuleFormPage";

const MODULE = {
  id: "module-1",
  translation_group_id: "group-1",
  language: "de",
  title: "Phishing-Bewusstsein",
  description: "Wie man Phishing erkennt.",
  estimated_duration_minutes: 15,
  status: "draft",
  created_by: { id: "user-1", display_name: "Cora Manager" },
  last_edited_by: { id: "user-1", display_name: "Cora Manager" },
  created_at: "2026-09-01T00:00:00Z",
  updated_at: "2026-09-01T00:00:00Z",
};

const CORA = { id: "user-2", display_name: "Cora Manager" };
const ED = { id: "user-3", display_name: "Ed Itor" };

type Requested = { method: string; url: string; body: unknown };

function mockBackend(editors: { id: string; display_name: string }[]) {
  const requested: Requested[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      const method = init?.method ?? "GET";
      requested.push({
        method,
        url,
        body: init?.body ? JSON.parse(init.body as string) : undefined,
      });

      if (url.endsWith("/editing")) {
        return method === "DELETE"
          ? new Response(null, { status: 204 })
          : new Response(JSON.stringify({ editors }), { status: 200 });
      }
      if (url.endsWith("/pages")) {
        return new Response(
          JSON.stringify({ draft_revision: 1, schema_version: 1, pages: [] }),
          { status: 200 },
        );
      }
      if (method === "PATCH") return new Response(JSON.stringify(MODULE), { status: 200 });
      return new Response(JSON.stringify(MODULE), { status: 200 });
    }),
  );
  return requested;
}

function renderFormPage() {
  return render(
    <MemoryRouter initialEntries={["/content/module-1"]}>
      <Routes>
        <Route path="/content/:moduleId" element={<ModuleFormPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("initials", () => {
  it("takes the first and last initial of a name", () => {
    expect(initials("Cora Manager")).toBe("CM");
    expect(initials("Ada Byron Lovelace")).toBe("AL");
  });

  it("falls back to a single letter when there is only one word", () => {
    expect(initials("cora@example.com")).toBe("C");
  });
});

describe("ModuleEditorsPresence", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("en");
  });

  it("renders nothing when the author is alone", () => {
    const { container } = render(<ModuleEditorsPresence editors={[]} />);

    expect(container).toBeEmptyDOMElement();
  });

  it("names one other editor and warns what saving does", () => {
    render(<ModuleEditorsPresence editors={[CORA]} />);

    expect(screen.getByText("Cora Manager also has this module open.")).toBeInTheDocument();
    expect(
      screen.getByText("Saving will overwrite any changes they have made without warning them."),
    ).toBeInTheDocument();
  });

  it("names several other editors, in the plural", () => {
    render(<ModuleEditorsPresence editors={[CORA, ED]} />);

    expect(
      screen.getByText("Cora Manager, Ed Itor also have this module open."),
    ).toBeInTheDocument();
  });
});

describe("the authoring screen's presence and overwrite warning", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("en");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("announces who else has the module open", async () => {
    mockBackend([ED]);

    renderFormPage();

    expect(
      await screen.findByText("Ed Itor also has this module open."),
    ).toBeInTheDocument();
  });

  it("says nothing when nobody else is editing", async () => {
    mockBackend([]);

    renderFormPage();
    await screen.findByLabelText("Title");

    expect(screen.queryByText(/also has this module open/)).not.toBeInTheDocument();
  });

  it("saves straight away when the author is alone", async () => {
    const user = userEvent.setup();
    const requested = mockBackend([]);

    renderFormPage();
    await screen.findByLabelText("Title");
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(
      requested.some((request) => request.method === "PATCH"),
    ).toBe(true);
  });

  it("warns before a save that could overwrite someone else's work", async () => {
    const user = userEvent.setup();
    const requested = mockBackend([ED]);

    renderFormPage();
    await screen.findByText("Ed Itor also has this module open.");
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("Someone else is editing this module");
    expect(dialog).toHaveTextContent("Ed Itor has this module open.");
    // Nothing has been written yet — the author still gets to change their mind.
    expect(requested.some((request) => request.method === "PATCH")).toBe(false);
  });

  it("overwrites when the author confirms — this is a warning, not a lock", async () => {
    const user = userEvent.setup();
    const requested = mockBackend([ED]);

    renderFormPage();
    await screen.findByText("Ed Itor also has this module open.");
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    await user.click(await screen.findByRole("button", { name: "Save anyway" }));

    expect(requested.some((request) => request.method === "PATCH")).toBe(true);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("writes nothing when the author backs out", async () => {
    const user = userEvent.setup();
    const requested = mockBackend([ED]);

    renderFormPage();
    await screen.findByText("Ed Itor also has this module open.");
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    await user.click(await screen.findByRole("button", { name: "Cancel" }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(requested.some((request) => request.method === "PATCH")).toBe(false);
  });

  it("puts focus on the confirming button so the keyboard reaches the decision", async () => {
    const user = userEvent.setup();
    mockBackend([ED]);

    renderFormPage();
    await screen.findByText("Ed Itor also has this module open.");
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    expect(await screen.findByRole("button", { name: "Save anyway" })).toHaveFocus();
  });

  it("lets Escape back out of the warning", async () => {
    const user = userEvent.setup();
    const requested = mockBackend([ED]);

    renderFormPage();
    await screen.findByText("Ed Itor also has this module open.");
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    await screen.findByRole("dialog");
    await user.keyboard("{Escape}");

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(requested.some((request) => request.method === "PATCH")).toBe(false);
  });

  it("heartbeats on open and leaves on unmount, so a seat frees up promptly", async () => {
    const requested = mockBackend([]);

    const { unmount } = renderFormPage();
    await screen.findByLabelText("Title");
    unmount();

    const presence = requested.filter((request) => request.url.endsWith("/editing"));
    expect(presence.some((request) => request.method === "POST")).toBe(true);
    expect(presence.some((request) => request.method === "DELETE")).toBe(true);
  });
});
