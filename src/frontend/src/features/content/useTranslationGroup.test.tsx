import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import i18n from "../../i18n";
import "../../i18n";
import { useTranslationGroup } from "./useTranslationGroup";

function respond(link: { status: number; body: unknown }) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        return new Response(JSON.stringify(link.body), { status: link.status });
      }
      return new Response(
        JSON.stringify({ id: "g1", primary_module_id: "m1", variants: [] }),
        { status: 200 },
      );
    }),
  );
}

describe("useTranslationGroup link refusal for quizzes", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("en");
  });
  afterEach(() => vi.unstubAllGlobals());

  it.each([
    ["source", "The module you chose has no quiz"],
    ["group", "The module you chose has a quiz, but this translation group does not"],
  ])("names which side lacks a quiz (%s)", async (side, expected) => {
    respond({
      status: 409,
      body: { detail: { code: "quiz_presence_mismatch", lacking_side: side } },
    });
    const { result } = renderHook(() => useTranslationGroup("g1"));
    await waitFor(() => expect(result.current.group).not.toBeNull());

    await act(async () => {
      await result.current.link("m2");
    });

    expect(result.current.error).toContain(expected);
  });
});
