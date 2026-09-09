"""Server-side validation of a page body against the checked-in schema.

Every incoming document is validated here and **rejected on failure — never
sanitized and accepted**. There is deliberately no code path that strips a
node, a mark, or an attribute and stores what is left: silent repair is how a
document that the author never approved ends up in the record, and how an
attribute nobody audited ends up on the learner's page.

Client-side editor configuration is UX. This module is the control.
"""

import json
import re
from typing import Any

from prosemirror.model import Node

from app.content.schema import (
    CONSTRAINTS,
    allowed_mark_attrs,
    allowed_node_attrs,
    prosemirror_schema,
)

_LIMITS = CONSTRAINTS["limits"]
MAX_NODES: int = _LIMITS["maxNodes"]
MAX_DEPTH: int = _LIMITS["maxDepth"]
MAX_BYTES: int = _LIMITS["maxBytes"]

_HEADING_LEVELS = frozenset(CONSTRAINTS["headingLevels"])
_LINK_PROTOCOLS = frozenset(protocol.lower() for protocol in CONSTRAINTS["linkProtocols"])
# The checked-in schema and `_check_link_href` below must agree about which
# protocols are permitted; this catches a schema edit that forgets the code.
assert _LINK_PROTOCOLS == {"https:", "mailto:"}, _LINK_PROTOCOLS
_IMAGE_SRC = re.compile(CONSTRAINTS["imageSrcPattern"])

# The complete set of keys a ProseMirror node may carry in its JSON form.
# Anything else is a rejection rather than an ignored extra.
_NODE_KEYS = frozenset({"type", "attrs", "content", "marks", "text"})
_MARK_KEYS = frozenset({"type", "attrs"})

# Browsers strip leading control characters and whitespace before resolving a
# URL, so `\x01javascript:alert(1)` navigates exactly as `javascript:` does.
# Rather than replicate that normalization (and risk diverging from it), any
# URL carrying such a character is refused outright.
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x20\x7f]")

_MAX_ATTRIBUTE_TEXT = 2048


class DocumentValidationError(Exception):
    """A page body that does not conform to the schema. Always a 422."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def validate_document(raw: Any) -> dict[str, Any]:
    """Validate a page body and return it in canonical form.

    Raises `DocumentValidationError` on anything that does not conform. The
    returned document is prosemirror-py's own round-trip of the input, so what
    gets stored is the schema's canonical spelling of the document rather than
    whatever shape the client happened to send.
    """
    if not isinstance(raw, dict):
        raise DocumentValidationError("not_a_document", "A page body must be a document object.")

    _check_size(raw)
    _walk(raw, depth=1, counter=_NodeCounter())

    schema = prosemirror_schema()
    try:
        node = Node.from_json(schema, raw)
        node.check()
    except DocumentValidationError:
        raise
    except Exception as error:  # prosemirror-py raises ValueError/KeyError/TypeError
        raise DocumentValidationError(
            "schema_violation", f"The document does not conform to the schema: {error}"
        ) from error

    if node.type.name != "doc":
        raise DocumentValidationError("not_a_document", "A page body must be a `doc` node.")

    return node.to_json()


def extract_search_text(document: dict[str, Any]) -> str:
    """Concatenate the document's text nodes for the full-text index.

    Deliberately a tree walk rather than `jsonb_to_tsvector` over the raw
    document: that indexes every node's type discriminator (`doc`,
    `paragraph`, `text`, `link`) and every string attribute, including URL
    fragments, so a learner searching for "link" would match every page in the
    system.
    """
    pieces: list[str] = []

    def visit(node: Any) -> None:
        if not isinstance(node, dict):
            return
        if node.get("type") == "text" and isinstance(node.get("text"), str):
            pieces.append(node["text"])
        for child in node.get("content") or []:
            visit(child)

    visit(document)
    return " ".join(piece.strip() for piece in pieces if piece.strip())


class _NodeCounter:
    def __init__(self) -> None:
        self.count = 0

    def bump(self) -> None:
        self.count += 1
        if self.count > MAX_NODES:
            raise DocumentValidationError(
                "too_many_nodes", f"A page may hold at most {MAX_NODES} nodes."
            )


def _check_size(raw: dict[str, Any]) -> None:
    try:
        serialized = json.dumps(raw, separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError) as error:
        raise DocumentValidationError(
            "not_serializable", "A page body must be a JSON document."
        ) from error
    if len(serialized.encode("utf-8")) > MAX_BYTES:
        raise DocumentValidationError(
            "document_too_large", f"A page body may be at most {MAX_BYTES} bytes."
        )


def _walk(node: Any, *, depth: int, counter: _NodeCounter) -> None:
    if depth > MAX_DEPTH:
        raise DocumentValidationError(
            "too_deep", f"A page body may nest at most {MAX_DEPTH} levels deep."
        )
    if not isinstance(node, dict):
        raise DocumentValidationError("malformed_node", "Every node must be an object.")

    counter.bump()

    unknown_keys = set(node) - _NODE_KEYS
    if unknown_keys:
        raise DocumentValidationError(
            "unknown_node_key", f"Unknown key on a node: {min(unknown_keys)!r}."
        )

    node_type = node.get("type")
    node_attrs = allowed_node_attrs()
    if not isinstance(node_type, str) or node_type not in node_attrs:
        raise DocumentValidationError("unknown_node_type", f"Unknown node type: {node_type!r}.")

    attrs = node.get("attrs")
    if attrs is not None:
        if not isinstance(attrs, dict):
            raise DocumentValidationError("malformed_attrs", "A node's `attrs` must be an object.")
        unknown_attrs = set(attrs) - node_attrs[node_type]
        if unknown_attrs:
            raise DocumentValidationError(
                "unknown_attribute",
                f"Unknown attribute {min(unknown_attrs)!r} on node {node_type!r}.",
            )
        _check_node_attrs(node_type, attrs)

    if node_type == "text":
        text = node.get("text")
        if not isinstance(text, str) or text == "":
            raise DocumentValidationError(
                "malformed_text", "A `text` node must carry non-empty text."
            )
    elif "text" in node:
        raise DocumentValidationError(
            "malformed_text", f"Only a `text` node may carry text, not {node_type!r}."
        )

    marks = node.get("marks")
    if marks is not None:
        if not isinstance(marks, list):
            raise DocumentValidationError("malformed_marks", "A node's `marks` must be an array.")
        for mark in marks:
            _check_mark(mark)

    content = node.get("content")
    if content is not None:
        if not isinstance(content, list):
            raise DocumentValidationError(
                "malformed_content", "A node's `content` must be an array."
            )
        for child in content:
            _walk(child, depth=depth + 1, counter=counter)


def _check_mark(mark: Any) -> None:
    if not isinstance(mark, dict):
        raise DocumentValidationError("malformed_mark", "Every mark must be an object.")

    unknown_keys = set(mark) - _MARK_KEYS
    if unknown_keys:
        raise DocumentValidationError(
            "unknown_mark_key", f"Unknown key on a mark: {min(unknown_keys)!r}."
        )

    mark_type = mark.get("type")
    mark_attrs = allowed_mark_attrs()
    if not isinstance(mark_type, str) or mark_type not in mark_attrs:
        raise DocumentValidationError("unknown_mark_type", f"Unknown mark type: {mark_type!r}.")

    attrs = mark.get("attrs")
    if attrs is None:
        return
    if not isinstance(attrs, dict):
        raise DocumentValidationError("malformed_attrs", "A mark's `attrs` must be an object.")
    unknown_attrs = set(attrs) - mark_attrs[mark_type]
    if unknown_attrs:
        raise DocumentValidationError(
            "unknown_attribute",
            f"Unknown attribute {min(unknown_attrs)!r} on mark {mark_type!r}.",
        )

    if mark_type == "link":
        _check_link_href(attrs.get("href"))


def _check_node_attrs(node_type: str, attrs: dict[str, Any]) -> None:
    if node_type == "heading" and "level" in attrs:
        if attrs["level"] not in _HEADING_LEVELS:
            raise DocumentValidationError(
                "bad_attribute",
                f"A heading level must be one of {sorted(_HEADING_LEVELS)}.",
            )
    elif node_type == "orderedList" and "start" in attrs:
        start = attrs["start"]
        if not isinstance(start, int) or isinstance(start, bool) or start < 1:
            raise DocumentValidationError(
                "bad_attribute", "An ordered list's `start` must be a positive integer."
            )
    elif node_type == "codeBlock" and "language" in attrs:
        _check_optional_text(attrs["language"], "codeBlock.language")
    elif node_type == "image":
        _check_image_src(attrs.get("src"))
        _check_optional_text(attrs.get("alt"), "image.alt")
        _check_optional_text(attrs.get("title"), "image.title")


def _check_optional_text(value: Any, label: str) -> None:
    if value is None:
        return
    if not isinstance(value, str):
        raise DocumentValidationError("bad_attribute", f"{label} must be a string or null.")
    if len(value) > _MAX_ATTRIBUTE_TEXT:
        raise DocumentValidationError(
            "bad_attribute", f"{label} may be at most {_MAX_ATTRIBUTE_TEXT} characters."
        )


def _check_link_href(href: Any) -> None:
    """`https:`, `mailto:`, and site-relative paths — nothing else.

    Tiptap's own `protocols`/`isAllowedUri` options are not relied on: they are
    client-side, an author's browser is not the only thing that can POST here,
    and their documentation makes no security claim.
    """
    if not isinstance(href, str) or href == "":
        raise DocumentValidationError("bad_href", "A link needs an `href`.")
    if len(href) > _MAX_ATTRIBUTE_TEXT:
        raise DocumentValidationError(
            "bad_href", f"A link `href` may be at most {_MAX_ATTRIBUTE_TEXT} characters."
        )
    if _CONTROL_CHARACTERS.search(href):
        raise DocumentValidationError(
            "bad_href", "A link `href` may not contain whitespace or control characters."
        )

    if href.startswith("/"):
        # A site-relative path — but not `//host`, which is protocol-relative
        # and leaves the platform's own origin, nor `/\host`, which several
        # browsers treat identically to `//host`.
        if href[1:2] in {"/", "\\"}:
            raise DocumentValidationError(
                "bad_href", "A protocol-relative link is not allowed; use an https: URL."
            )
        return

    # Matched as a literal prefix rather than by parsing out a scheme: an
    # `https:` with no authority (`https:evil`) parses as scheme "https" but
    # resolves relative to the current host, which is not what "an https: URL"
    # is meant to permit here.
    lowered = href.lower()
    if lowered.startswith(("https://", "mailto:")):
        return
    raise DocumentValidationError(
        "bad_href",
        "A link must be an https: URL, a mailto: address, or a site-relative path.",
    )


def _check_image_src(src: Any) -> None:
    """Only this platform's own asset paths.

    The asset endpoint itself arrives with module assets; until then nothing
    matches this pattern, which is the intended state — an author cannot point
    a page at an image on someone else's server.
    """
    if not isinstance(src, str) or src == "":
        raise DocumentValidationError("bad_src", "An image needs a `src`.")
    if _CONTROL_CHARACTERS.search(src) or not _IMAGE_SRC.fullmatch(src):
        raise DocumentValidationError(
            "bad_src", "An image `src` must be one of this platform's own asset paths."
        )
