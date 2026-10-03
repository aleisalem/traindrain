import { renderToReactElement } from "@tiptap/static-renderer/pm/react";

import { pageExtensions } from "../../content/extensions";
import type { PageDocument } from "../../content/schema";

type Props = {
  document: PageDocument;
};

/**
 * A page rendered as a learner will see it.
 *
 * Rendering goes exclusively through `renderToReactElement`, which builds
 * React elements from the document tree. No HTML string is produced anywhere
 * on this path, so `dangerouslySetInnerHTML` never appears — and an oxlint
 * rule fails the build if it ever does.
 */
export function PagePreview({ document }: Props) {
  return (
    <div className="page-prose">
      {renderToReactElement({ content: document, extensions: pageExtensions })}
    </div>
  );
}
