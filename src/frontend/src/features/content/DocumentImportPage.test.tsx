import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import i18n from "../../i18n";
import "../../i18n";
import { DocumentImportPage } from "./DocumentImportPage";

const IMPORT_URL = "/api/content/modules/document-import";

function markdownFile(name = "notes.md") {
  return new File(["# Title\n\nSome content."], name, { type: "text/markdown" });
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/content/import"]}>
      <Routes>
        <Route path="/content/import" element={<DocumentImportPage />} />
        <Route path="/content/:moduleId" element={<div>module editor</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

const MODULE = {
  id: "module-9",
  translation_group_id: "group-9",
  language: "en",
  title: "Imported Module",
  description: null,
  estimated_duration_minutes: null,
  status: "draft",
  catalog_visible: false,
  current_version_number: null,
  deleted_version_number: null,
  tags: [],
  created_by: { id: "user-1", display_name: "Cora Manager" },
  last_edited_by: { id: "user-1", display_name: "Cora Manager" },
  created_at: "2026-09-01T00:00:00Z",
  updated_at: "2026-09-01T00:00:00Z",
};

describe("DocumentImportPage", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("en");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("uploads the chosen file and language, then shows the conversion report", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      expect(url).toBe(IMPORT_URL);
      expect(init?.method).toBe("POST");
      const form = init?.body as FormData;
      expect(form.get("file")).toBeInstanceOf(File);
      expect(form.get("language")).toBe("de");
      return new Response(
        JSON.stringify({
          module: MODULE,
          conversion_report: [{ code: "table_dropped", message: "A table was dropped." }],
        }),
        { status: 201, headers: { "Content-Type": "application/json" } },
      );
    });
    vi.stubGlobal("fetch", fetchMock);

    renderPage();

    const fileInput = screen.getByLabelText("File") as HTMLInputElement;
    await user.upload(fileInput, markdownFile());
    await user.selectOptions(screen.getByLabelText("Language"), "de");
    await user.click(screen.getByRole("button", { name: "Import" }));

    expect(await screen.findByText("Document imported")).toBeInTheDocument();
    expect(screen.getByText("A table was dropped.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open module" })).toHaveAttribute(
      "href",
      "/content/module-9",
    );
  });

  it("shows a localized message for a known rejection code", async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({ detail: { code: "encrypted_pdf", message: "nope" } }),
            { status: 422, headers: { "Content-Type": "application/json" } },
          ),
      ),
    );

    renderPage();

    await user.upload(screen.getByLabelText("File"), markdownFile("doc.pdf"));
    await user.click(screen.getByRole("button", { name: "Import" }));

    expect(
      await screen.findByText("Password-protected PDFs cannot be imported."),
    ).toBeInTheDocument();
  });

  it("falls back to a generic error on an unrecognised failure", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("fetch", vi.fn(async () => new Response(null, { status: 500 })));

    renderPage();

    await user.upload(screen.getByLabelText("File"), markdownFile());
    await user.click(screen.getByRole("button", { name: "Import" }));

    expect(
      await screen.findByText("Something went wrong. Please try again."),
    ).toBeInTheDocument();
  });

  it("disables the submit button until a file is chosen", () => {
    renderPage();
    expect(screen.getByRole("button", { name: "Import" })).toBeDisabled();
  });
});
