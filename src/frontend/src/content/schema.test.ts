import { getSchema } from "@tiptap/core";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import { pageExtensions } from "./extensions";
import { ALLOWED_MARKS, ALLOWED_NODES, HEADING_LEVELS } from "./schema";

// Resolved from the frontend package root, which is vitest's working
// directory — `import.meta.url` is an http: URL under jsdom.
const FRONTEND_COPY = resolve(process.cwd(), "src/content/prosemirrorSchema.json");
const BACKEND_CANONICAL = resolve(
  process.cwd(),
  "../backend/app/content/prosemirror_schema.json",
);

describe("the checked-in ProseMirror schema", () => {
  it("is byte-identical to the backend's canonical copy", () => {
    // One schema, two Docker build contexts. The backend file is canonical;
    // this test is what keeps the editor's copy from drifting away from the
    // validator that will reject its output.
    expect(readFileSync(FRONTEND_COPY, "utf8")).toBe(readFileSync(BACKEND_CANONICAL, "utf8"));
  });

  it("describes exactly the nodes and marks the editor can produce", () => {
    const editorSchema = getSchema(pageExtensions);

    expect(Object.keys(editorSchema.nodes).sort()).toEqual([...ALLOWED_NODES].sort());
    expect(Object.keys(editorSchema.marks).sort()).toEqual([...ALLOWED_MARKS].sort());
  });

  it("gives the editor's link mark only the href the schema allows", () => {
    const editorSchema = getSchema(pageExtensions);

    // An extra attribute here would be a document the server rejects rather
    // than strips — the editor must not be able to emit one.
    expect(Object.keys(editorSchema.marks.link.spec.attrs ?? {})).toEqual(["href"]);
  });

  it("restricts headings to the levels the schema allows", () => {
    expect(HEADING_LEVELS).toEqual([2, 3, 4]);
  });
});
