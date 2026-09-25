import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import i18n from "../../i18n";
import "../../i18n";
import { TranslationsPanel } from "./TranslationsPanel";
import type { ModuleBody, TranslationGroupBody } from "./types";
import type { TranslationGroupState } from "./useTranslationGroup";

function moduleBody(overrides: Partial<ModuleBody> = {}): ModuleBody {
  return {
    id: "module-en",
    translation_group_id: "group-1",
    language: "en",
    title: "Phishing Awareness",
    description: "How to spot a phish.",
    estimated_duration_minutes: 15,
    status: "draft",
    catalog_visible: false,
    current_version_number: null,
    deleted_version_number: null,
    tags: [],
    created_by: { id: "user-1", display_name: "Cora Manager" },
    last_edited_by: { id: "user-1", display_name: "Cora Manager" },
    created_at: "2026-09-01T00:00:00Z",
    updated_at: "2026-09-01T00:00:00Z",
    ...overrides,
  };
}

function groupBody(overrides: Partial<TranslationGroupBody> = {}): TranslationGroupBody {
  return {
    id: "group-1",
    primary_module_id: "module-en",
    variants: [moduleBody()],
    ...overrides,
  };
}

function stateWith(overrides: Partial<TranslationGroupState> = {}): TranslationGroupState {
  return {
    group: groupBody(),
    loading: false,
    loadError: false,
    busy: false,
    error: null,
    link: vi.fn().mockResolvedValue(true),
    setPrimary: vi.fn().mockResolvedValue(true),
    clearError: vi.fn(),
    ...overrides,
  };
}

function mockModuleList(modules: ModuleBody[]) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify(modules), { status: 200 })),
  );
}

describe("TranslationsPanel", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("en");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("lists every variant and marks the primary one", async () => {
    mockModuleList([]);
    const translations = stateWith({
      group: groupBody({
        variants: [
          moduleBody({ id: "module-en", language: "en", title: "Phishing Awareness" }),
          moduleBody({ id: "module-de", language: "de", title: "Phishing-Bewusstsein" }),
        ],
      }),
    });

    render(<TranslationsPanel translations={translations} />);

    expect(await screen.findByText("Phishing Awareness")).toBeInTheDocument();
    expect(screen.getByText("Phishing-Bewusstsein")).toBeInTheDocument();
    expect(screen.getByText("Primary")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Make primary" })).toBeInTheDocument();
  });

  it("nominates a new primary when asked", async () => {
    mockModuleList([]);
    const user = userEvent.setup();
    const translations = stateWith({
      group: groupBody({
        variants: [
          moduleBody({ id: "module-en", language: "en" }),
          moduleBody({ id: "module-de", language: "de", title: "Andere Sprache" }),
        ],
      }),
    });

    render(<TranslationsPanel translations={translations} />);
    await user.click(await screen.findByRole("button", { name: "Make primary" }));

    expect(translations.setPrimary).toHaveBeenCalledWith("module-de");
  });

  it("offers only modules that would not immediately collide on language", async () => {
    mockModuleList([
      moduleBody({ id: "module-en", language: "en" }), // already this group's own variant
      moduleBody({ id: "outsider-de", translation_group_id: "group-2", language: "de", title: "Outsider DE" }),
      moduleBody({
        id: "outsider-en",
        translation_group_id: "group-3",
        language: "en",
        title: "Outsider EN",
      }),
      moduleBody({
        id: "outsider-deleted",
        translation_group_id: "group-4",
        language: "fr",
        status: "deleted",
        title: "Outsider Deleted",
      }),
    ]);
    const translations = stateWith();

    render(<TranslationsPanel translations={translations} />);

    // The group's own English variant, the outsider already in English (would
    // collide), and the deleted outsider are all withheld from the choice.
    await waitFor(() => {
      expect(screen.getByRole("combobox")).toBeInTheDocument();
    });
    const options = screen.getAllByRole("option").map((option) => option.textContent);
    expect(options).toContain("Outsider DE (German)");
    expect(options).not.toContain("Outsider EN (English)");
    expect(options).not.toContain("Outsider Deleted (French)");
    expect(options.some((label) => label?.startsWith("Phishing Awareness"))).toBe(false);
  });

  it("links the selected module in as a variant", async () => {
    mockModuleList([
      moduleBody({ id: "outsider-de", translation_group_id: "group-2", language: "de", title: "Outsider DE" }),
    ]);
    const user = userEvent.setup();
    const translations = stateWith();

    render(<TranslationsPanel translations={translations} />);
    await user.selectOptions(await screen.findByRole("combobox"), "outsider-de");
    await user.click(screen.getByRole("button", { name: "Link as translation" }));

    expect(translations.link).toHaveBeenCalledWith("outsider-de");
  });

  it("shows the server's refusal", async () => {
    mockModuleList([]);
    const translations = stateWith({ error: "This group already has a variant in that language." });

    render(<TranslationsPanel translations={translations} />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This group already has a variant in that language.",
    );
  });

  it("renders nothing while the group is still loading", () => {
    const translations = stateWith({ group: null, loading: true });

    const { container } = render(<TranslationsPanel translations={translations} />);

    expect(container).toBeEmptyDOMElement();
  });
});
