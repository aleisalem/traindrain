import type { JSONContent } from "@tiptap/core";

import schemaDocument from "./prosemirrorSchema.json";

/**
 * The checked-in ProseMirror schema — the same file the backend validator
 * reads, mirrored here so the Docker build contexts stay independent.
 * `schema.drift.test.ts` fails if the two copies ever diverge.
 *
 * The editor is configured *from* this file (see `extensions.ts`), so
 * widening the editor without widening the schema is not possible: the
 * server would reject the document anyway.
 */

/**
 * A page body. Structurally this is Tiptap's own JSON shape — the guarantee
 * that it holds only the nodes and marks above is the server's, not
 * TypeScript's, which is the whole point of validating server-side.
 */
export type PageDocument = JSONContent;

type SchemaDocument = {
  schemaVersion: number;
  spec: {
    nodes: Record<string, { attrs?: Record<string, unknown> }>;
    marks: Record<string, { attrs?: Record<string, unknown> }>;
  };
  constraints: {
    headingLevels: number[];
    linkProtocols: string[];
    imageSrcPattern: string;
    limits: {
      maxNodes: number;
      maxDepth: number;
      maxBytes: number;
      maxPageTitleLength: number;
      maxPagesPerModule: number;
    };
  };
};

const schema = schemaDocument as SchemaDocument;

export const SCHEMA_VERSION = schema.schemaVersion;
export const HEADING_LEVELS = schema.constraints.headingLevels as (2 | 3 | 4)[];
export const LIMITS = schema.constraints.limits;
export const ALLOWED_NODES = Object.keys(schema.spec.nodes);
export const ALLOWED_MARKS = Object.keys(schema.spec.marks);

/** An empty page body — one empty paragraph, the smallest valid document. */
export function emptyDocument(): PageDocument {
  return { type: "doc", content: [{ type: "paragraph" }] };
}
