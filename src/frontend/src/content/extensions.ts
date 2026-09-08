import Image from "@tiptap/extension-image";
import Link from "@tiptap/extension-link";
import StarterKit from "@tiptap/starter-kit";

import { HEADING_LEVELS } from "./schema";

/**
 * A Link mark carrying `href` and nothing else.
 *
 * Tiptap's Link ships `target`, `rel`, and `class` attributes too. The
 * checked-in schema has only `href`, and the server rejects an unknown
 * attribute rather than stripping it — so an editor that emitted `target`
 * would produce documents the server refuses. Narrowing the mark here keeps
 * the editor honest.
 *
 * Note what this is *not*: Tiptap's `protocols`/`isAllowedUri` options are not
 * the security control. Anything can POST a document; `href` validation runs
 * server-side in `app/content/validation.py`.
 */
const HrefOnlyLink = Link.extend({
  addAttributes() {
    return {
      href: {
        default: null,
        parseHTML: (element) => element.getAttribute("href"),
        renderHTML: (attributes) =>
          attributes.href ? { href: attributes.href as string } : {},
      },
    };
  },
});

/**
 * The editor's extension set, matching the checked-in schema exactly.
 *
 * Everything StarterKit ships that the schema does not model is switched off:
 * a node the editor can produce but the schema does not allow is a document
 * the author writes and the server refuses to save.
 */
export const pageExtensions = [
  StarterKit.configure({
    heading: { levels: HEADING_LEVELS },
    // Not in the Release 1 node set.
    strike: false,
    underline: false,
    // Replaced below with an href-only Link.
    link: false,
    // Would append a paragraph node the author never typed.
    trailingNode: false,
  }),
  HrefOnlyLink.configure({
    openOnClick: false,
    // Belt and braces on the authoring side; the server is the actual gate.
    protocols: ["https", "mailto"],
  }),
  Image,
];
