"""Converting an uploaded Markdown, DOCX, or PDF file into draft page bodies.

Existing written material becomes training content without being retyped.
Conversion is lossy by nature — a `.docx` table has no equivalent in the
checked-in page schema, a PDF has no headings at all once its text is
extracted — so every converter here returns a `ConversionIssue` for anything
it dropped or altered, rather than losing it silently. `app.routes.document_import`
is what turns that into the response the importing author reads.

Three postures carried over from `app.content.uploads` and `app.content.transfer`,
because this is the same kind of hostile-input surface:

* Nothing here ever makes a network request. A Markdown or DOCX image that
  points somewhere else is dropped, never fetched — resolving it would hand
  an SSRF sink to anyone who can upload a file.
* A `.docx` is a zip archive wearing a different extension, so it gets the
  same zip-bomb defenses (entry count, compression ratio, total size) as a
  native `.zip` import before `python-docx` ever opens it.
* Every page this module builds still goes through the exact same
  server-side ProseMirror validator (`app.content.validate_document`)
  authored content goes through, in `app.routes.document_import` — nothing
  here is trusted as "already safe" for having come out of a converter.

Markdown's raw-HTML passthrough is disabled outright (`options["html"] =
False`), per markdown-it's own security guidance for untrusted input, rather
than relied on to render safely — with it off, markdown-it never emits an
`html_block`/`html_inline` token at all, and a literal `<script>` in the
source becomes ordinary text. The `nh3`-based sanitizer below exists as the
second, independent layer for exactly that node type, on the chance a future
markdown-it version or plugin reintroduces it; `nh3` appears only on this
import path and never on the authoring write path, and never with its
default allowlist extended.
"""

from __future__ import annotations

import io
import re
import uuid
import zipfile
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any, Literal

import nh3
from docx import Document as DocxDocument
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.hyperlink import Hyperlink
from markdown_it import MarkdownIt
from markdown_it.tree import SyntaxTreeNode
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.content.schema import CONSTRAINTS
from app.content.uploads import UploadRejected, sniff_upload

DocumentFormat = Literal["markdown", "docx", "pdf"]

_LIMITS = CONSTRAINTS["limits"]
_MAX_PAGES: int = _LIMITS["maxPagesPerModule"]
# Shared by a module's own title (`ModuleCreateRequest.title`) and a page's
# (`maxPageTitleLength`) — both happen to be 200 today, checked once here
# rather than trusted to stay in sync by coincidence.
_MAX_TITLE: int = 200
assert _LIMITS["maxPageTitleLength"] == _MAX_TITLE, "page title limit drifted from document_import's assumption"

_HEADING_STYLE_RE = re.compile(r"^Heading (\d)$")
_WORD_MAIN_PART = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
_MAX_CONTENT_TYPES_BYTES = 512 * 1024


class DocumentImportRejected(Exception):
    """A document that may not be converted. Always a 4xx, never a partial import."""

    def __init__(self, code: str, message: str, *, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class ConversionIssue:
    code: str
    message: str


@dataclass(frozen=True)
class ConvertedImage:
    """An image extracted from the source document, not yet an uploaded asset.

    `placeholder` is an opaque token, never a real asset URL, planted as an
    `image` node's `src` — the schema's own `imageSrcPattern` would reject it
    as-is. `app.routes.document_import` uploads the bytes, then rewrites every
    occurrence of `placeholder` to the real asset URL before the page is
    validated and stored.
    """

    placeholder: str
    data: bytes
    filename: str


@dataclass(frozen=True)
class ConvertedPage:
    title: str
    body: dict[str, Any]


@dataclass(frozen=True)
class ConvertedDocument:
    title: str
    pages: list[ConvertedPage]
    images: list[ConvertedImage] = field(default_factory=list)
    issues: list[ConversionIssue] = field(default_factory=list)


# --- Format detection -------------------------------------------------------


def sniff_document_format(filename: str, data: bytes) -> DocumentFormat:
    """What kind of document this is, from its bytes — not its declared type.

    Same posture as `app.content.uploads.sniff_upload`: the extension has to
    agree with what the bytes actually are, rather than being trusted alone.
    """
    if not data:
        raise DocumentImportRejected("empty_file", "This file is empty.")

    basename = re.split(r"[\\/]", filename)[-1].strip()
    _, _, extension = basename.rpartition(".")
    extension = extension.lower()

    if data.startswith(b"%PDF-"):
        if extension not in ("", "pdf"):
            raise DocumentImportRejected(
                "extension_mismatch",
                "This file's contents are a PDF, but its name does not end in .pdf.",
            )
        return "pdf"

    if data.startswith(b"PK\x03\x04"):
        if extension != "docx":
            raise DocumentImportRejected(
                "extension_mismatch",
                "This file's contents are a Word document, but its name does not end in .docx.",
            )
        return "docx"

    if extension not in ("md", "markdown", "txt", ""):
        raise DocumentImportRejected(
            "unrecognised_format",
            "Only Markdown (.md), Word (.docx), and PDF (.pdf) files can be imported.",
        )
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise DocumentImportRejected(
            "unrecognised_format", "This file is not valid UTF-8 Markdown text."
        ) from error
    return "markdown"


# --- Shared node builders ----------------------------------------------------
#
# Every helper here either returns a valid node/mark dict or `None` — never a
# node with a key it shouldn't have. Callers filter `None`s out rather than
# each re-deriving "was this actually empty".


def _text(text: str, marks: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    if not text:
        return None
    node: dict[str, Any] = {"type": "text", "text": text}
    if marks:
        node["marks"] = marks
    return node


def _paragraph(inline: list[dict[str, Any] | None]) -> dict[str, Any] | None:
    content = [node for node in inline if node is not None]
    return {"type": "paragraph", "content": content} if content else {"type": "paragraph"}


def _heading(level: int, inline: list[dict[str, Any] | None]) -> dict[str, Any] | None:
    content = [node for node in inline if node is not None]
    if not content:
        return None
    return {"type": "heading", "attrs": {"level": level}, "content": content}


def _code_block(text: str, language: str | None) -> dict[str, Any]:
    node: dict[str, Any] = {"type": "codeBlock", "attrs": {"language": language}}
    if text:
        node["content"] = [{"type": "text", "text": text}]
    return node


def _horizontal_rule() -> dict[str, Any]:
    return {"type": "horizontalRule"}


def _blockquote(blocks: list[dict[str, Any] | None]) -> dict[str, Any] | None:
    content = [block for block in blocks if block is not None]
    return {"type": "blockquote", "content": content} if content else None


def _list_item(blocks: list[dict[str, Any] | None]) -> dict[str, Any]:
    content = [block for block in blocks if block is not None]
    if not content:
        content = [{"type": "paragraph"}]
    return {"type": "listItem", "content": content}


def _bullet_list(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    return {"type": "bulletList", "content": items} if items else None


def _ordered_list(items: list[dict[str, Any]], *, start: int = 1) -> dict[str, Any] | None:
    if not items:
        return None
    node: dict[str, Any] = {"type": "orderedList", "content": items}
    if start != 1:
        node["attrs"] = {"start": start}
    return node


def _image(placeholder_src: str) -> dict[str, Any]:
    return {"type": "image", "attrs": {"src": placeholder_src, "alt": None, "title": None}}


_ALLOWED_LINK_PREFIXES = ("https://", "mailto:")


def _is_allowed_href(href: str) -> bool:
    """Mirrors `app.content.validation._check_link_href`'s allowlist.

    Kept as its own copy rather than an import: this decides whether to keep
    a link *before* the document reaches the validator, so a disallowed one
    can be reported and dropped to plain text instead of failing the whole
    import. The validator is still the control — this is only what makes a
    lossy-but-successful import possible for the common case of a `ftp:` or
    bare `www.` link a hand-written document happens to contain.
    """
    if not href or any(ord(char) < 0x21 or ord(char) == 0x7F for char in href):
        return False
    if href.startswith("/"):
        return href[1:2] not in ("/", "\\")
    return href.lower().startswith(_ALLOWED_LINK_PREFIXES)


def _link_mark(href: str) -> dict[str, Any] | None:
    if not _is_allowed_href(href):
        return None
    return {"type": "link", "attrs": {"href": href}}


def _plain_text(inline_nodes: list[dict[str, Any]]) -> str:
    return "".join(node.get("text", "") for node in inline_nodes if node.get("type") == "text")


def _title_from_filename(filename: str) -> str:
    stem = re.split(r"[\\/]", filename)[-1].strip()
    stem = stem.rsplit(".", 1)[0] if "." in stem else stem
    words = [word for word in re.split(r"[_\-\s]+", stem) if word]
    title = " ".join(word[:1].upper() + word[1:] for word in words)
    return title or "Untitled import"


def _clamp_title(title: str | None, issues: list[ConversionIssue], *, fallback: str) -> str:
    stripped = (title or "").strip() or fallback.strip()
    if len(stripped) > _MAX_TITLE:
        issues.append(
            ConversionIssue(
                "title_truncated",
                f"A title was longer than {_MAX_TITLE} characters and was shortened.",
            )
        )
        return stripped[:_MAX_TITLE]
    return stripped


def _clamp_heading_level(level: int, issues: list[ConversionIssue]) -> int:
    if level in (2, 3, 4):
        return level
    clamped = 2 if level <= 1 else 4
    issues.append(
        ConversionIssue(
            "heading_level_adjusted",
            f"A level-{level} heading is outside the supported range (2-4) and was "
            f"converted to a level-{clamped} heading.",
        )
    )
    return clamped


def _note_once(issues: list[ConversionIssue], code: str, message: str) -> None:
    if not any(issue.code == code for issue in issues):
        issues.append(ConversionIssue(code, message))


# The only HTML tags a sanitized fragment is allowed to keep any *meaning*
# from — everything else `nh3`'s allowlist still permits (headings, lists,
# divs, spans, ...) contributes its text content only. Deliberately narrow:
# the goal is never silently losing text to a dropped tag, not reproducing
# arbitrary HTML structure the page schema has no block-level home for.
_HTML_MARK_TAGS = {"b": "bold", "strong": "bold", "i": "italic", "em": "italic", "code": "code"}


class _SanitizedHtmlToNodes(HTMLParser):
    """Walks a sanitized HTML fragment into a flat list of PM inline nodes.

    Only ever fed `nh3.clean`'s own output, so `<script>`/`<style>`/event
    attributes are already gone before this runs — this is the "parsed to a
    node tree" half of that sanitize-then-parse pipeline, not a second
    security boundary.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.nodes: list[dict[str, Any]] = []
        self._marks: list[dict[str, Any]] = []
        self._link_hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _HTML_MARK_TAGS:
            self._marks.append({"type": _HTML_MARK_TAGS[tag]})
        elif tag == "a":
            self._link_hrefs.append(next((value or "" for name, value in attrs if name == "href"), ""))

    def handle_endtag(self, tag: str) -> None:
        if tag in _HTML_MARK_TAGS and self._marks:
            self._marks.pop()
        elif tag == "a" and self._link_hrefs:
            self._link_hrefs.pop()

    def handle_data(self, data: str) -> None:
        marks = list(self._marks)
        if self._link_hrefs:
            link = _link_mark(self._link_hrefs[-1])
            if link is not None:
                marks.append(link)
        node = _text(data, marks or None)
        if node:
            self.nodes.append(node)


def _sanitize_raw_html(html_source: str) -> list[dict[str, Any]]:
    """Defense in depth for an `html_block`/`html_inline` token, should one ever appear.

    `nh3.clean` runs on its own default allowlist — never extended with
    `svg`, `math`, `style`, `script`, `iframe`, `textarea`, or `title` — and
    the cleaned result is then parsed into ProseMirror inline nodes by
    `_SanitizedHtmlToNodes`, rather than reduced to inert plain text: `<b>`,
    `<em>`, `<code>`, and an `<a href>` that passes `_is_allowed_href` survive
    as the equivalent mark, everything else as plain text.
    """
    cleaned = nh3.clean(html_source)
    parser = _SanitizedHtmlToNodes()
    parser.feed(cleaned)
    parser.close()
    return parser.nodes


def _group_sections(
    events: list[tuple[str, Any]],
) -> list[tuple[str | None, list[dict[str, Any]]]]:
    """Split a flat event stream into (heading-text-or-None, blocks) sections.

    One `("page_break", heading_text)` event starts each new section; every
    other event is a block appended to the current one. There is always one
    more section than there are page breaks — the leading section (before the
    first page break, `heading` is `None`) included.
    """
    sections: list[tuple[str | None, list[dict[str, Any]]]] = []
    current_heading: str | None = None
    current_blocks: list[dict[str, Any]] = []
    for kind, payload in events:
        if kind == "page_break":
            sections.append((current_heading, current_blocks))
            current_heading, current_blocks = payload, []
        else:
            current_blocks.append(payload)
    sections.append((current_heading, current_blocks))
    return sections


def _finalize_pages(
    sections: list[tuple[str | None, list[dict[str, Any]]]],
    issues: list[ConversionIssue],
    *,
    module_title: str,
) -> list[tuple[str, list[dict[str, Any]]]]:
    pages: list[tuple[str, list[dict[str, Any]]]] = []
    for heading, blocks in sections:
        if not blocks:
            if heading is not None:
                issues.append(
                    ConversionIssue(
                        "empty_section_dropped",
                        f"The section {heading!r} had no content and was dropped.",
                    )
                )
            continue
        title = _clamp_title(heading, issues, fallback=module_title)
        pages.append((title, blocks))
    return pages


def _enforce_page_count(pages: list[tuple[str, list[dict[str, Any]]]]) -> None:
    if not pages:
        raise DocumentImportRejected("empty_document", "This document has no content to import.")
    if len(pages) > _MAX_PAGES:
        raise DocumentImportRejected(
            "too_many_pages",
            f"A module may hold at most {_MAX_PAGES} pages; this document would produce "
            f"{len(pages)}.",
            status_code=409,
        )


# --- Markdown ----------------------------------------------------------------


def convert_markdown(data: bytes, *, filename: str) -> ConvertedDocument:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise DocumentImportRejected(
            "not_utf8", "This Markdown file is not valid UTF-8."
        ) from error

    md = MarkdownIt("js-default")
    # Explicit, not relied on as the preset's default: raw HTML is refused
    # outright rather than rendered, per markdown-it's own security guidance.
    md.options["html"] = False
    md.options["linkify"] = False
    tree = SyntaxTreeNode(md.parse(text))

    issues: list[ConversionIssue] = []
    extracted_title, events = _markdown_events(list(tree.children), issues)
    module_title = _clamp_title(extracted_title, issues, fallback=_title_from_filename(filename))
    if extracted_title is None:
        issues.append(
            ConversionIssue(
                "title_inferred_from_filename",
                "No top-level heading was found; the module title was taken from the file name.",
            )
        )

    pages = _finalize_pages(_group_sections(events), issues, module_title=module_title)
    _enforce_page_count(pages)

    converted_pages = [
        ConvertedPage(title=title, body={"type": "doc", "content": blocks})
        for title, blocks in pages
    ]
    return ConvertedDocument(title=module_title, pages=converted_pages, issues=issues)


def _markdown_events(
    top_nodes: list[SyntaxTreeNode], issues: list[ConversionIssue]
) -> tuple[str | None, list[tuple[str, Any]]]:
    events: list[tuple[str, Any]] = []
    title: str | None = None
    start_index = 0

    if top_nodes and top_nodes[0].type == "heading" and int(top_nodes[0].tag[1]) == 1:
        inline = _markdown_inline_children(top_nodes[0])
        text_nodes = _markdown_inline_to_pm(inline, issues)
        title = _plain_text(text_nodes).strip() or None
        start_index = 1

    for node in top_nodes[start_index:]:
        if node.type == "heading" and int(node.tag[1]) == 2:
            inline = _markdown_inline_children(node)
            text_nodes = _markdown_inline_to_pm(inline, issues)
            events.append(("page_break", _plain_text(text_nodes).strip()))
            continue
        block = _convert_markdown_node(node, issues)
        if block is not None:
            events.append(("block", block))
    return title, events


def _markdown_inline_children(node: SyntaxTreeNode) -> list[SyntaxTreeNode]:
    return node.children[0].children if node.children else []


def _convert_markdown_children(
    nodes: list[SyntaxTreeNode], issues: list[ConversionIssue]
) -> list[dict[str, Any]]:
    blocks = [_convert_markdown_node(node, issues) for node in nodes]
    return [block for block in blocks if block is not None]


def _convert_markdown_node(
    node: SyntaxTreeNode, issues: list[ConversionIssue]
) -> dict[str, Any] | None:
    if node.type == "heading":
        level = _clamp_heading_level(int(node.tag[1]), issues)
        inline = _markdown_inline_children(node)
        return _heading(level, _markdown_inline_to_pm(inline, issues))
    if node.type == "paragraph":
        inline = _markdown_inline_children(node)
        if len(inline) == 1 and inline[0].type == "image":
            _report_dropped_image(inline[0].attrs.get("src"), issues)
            return None
        return _paragraph(_markdown_inline_to_pm(inline, issues))
    if node.type == "bullet_list":
        items = [
            _list_item(_convert_markdown_children(item.children, issues))
            for item in node.children
        ]
        return _bullet_list(items)
    if node.type == "ordered_list":
        items = [
            _list_item(_convert_markdown_children(item.children, issues))
            for item in node.children
        ]
        start = node.attrs.get("start", 1) if isinstance(node.attrs.get("start", 1), int) else 1
        return _ordered_list(items, start=start)
    if node.type == "blockquote":
        return _blockquote(_convert_markdown_children(node.children, issues))
    if node.type in ("fence", "code_block"):
        language = None
        if node.type == "fence" and node.info:
            language = node.info.strip().split()[0] or None
        return _code_block(node.content, language)
    if node.type == "hr":
        return _horizontal_rule()
    if node.type in ("html_block",):
        # Never actually reached with `html: False` above — see the module
        # docstring. Kept as a second, independent layer rather than assumed
        # unreachable forever, and exercised directly in
        # `test_document_import.py` since the public import path can't reach it.
        issues.append(
            ConversionIssue(
                "raw_html_stripped",
                "Raw HTML in the source was sanitized and reduced to its supported "
                "formatting subset.",
            )
        )
        return _paragraph(_sanitize_raw_html(node.content))
    issues.append(
        ConversionIssue(
            "unsupported_block_dropped", f"A {node.type!r} element could not be converted and was dropped."
        )
    )
    return None


def _report_dropped_image(src: Any, issues: list[ConversionIssue]) -> None:
    label = src if isinstance(src, str) and src else "unknown"
    issues.append(
        ConversionIssue(
            "image_reference_dropped",
            f"An image reference ({label}) cannot be fetched during import and was dropped.",
        )
    )


def _markdown_inline_to_pm(
    nodes: list[SyntaxTreeNode],
    issues: list[ConversionIssue],
    active_marks: tuple[dict[str, Any], ...] = (),
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for node in nodes:
        if node.type == "text":
            appended = _text(node.content, list(active_marks) or None)
            if appended:
                result.append(appended)
        elif node.type == "code_inline":
            appended = _text(node.content, [*active_marks, {"type": "code"}])
            if appended:
                result.append(appended)
        elif node.type == "strong":
            result.extend(
                _markdown_inline_to_pm(node.children, issues, (*active_marks, {"type": "bold"}))
            )
        elif node.type == "em":
            result.extend(
                _markdown_inline_to_pm(node.children, issues, (*active_marks, {"type": "italic"}))
            )
        elif node.type == "link":
            href = node.attrs.get("href", "") or ""
            mark = _link_mark(href)
            if mark is None:
                _note_once(
                    issues,
                    "link_dropped",
                    "A link used an unsupported address and was kept as plain text.",
                )
                result.extend(_markdown_inline_to_pm(node.children, issues, active_marks))
            else:
                result.extend(
                    _markdown_inline_to_pm(node.children, issues, (*active_marks, mark))
                )
        elif node.type == "softbreak":
            appended = _text(" ", list(active_marks) or None)
            if appended:
                result.append(appended)
        elif node.type == "hardbreak":
            result.append({"type": "hardBreak"})
        elif node.type == "image":
            _report_dropped_image(node.attrs.get("src"), issues)
        elif node.type in ("html_inline",):
            # Same defense-in-depth posture as the `html_block` branch above.
            issues.append(
                ConversionIssue(
                    "raw_html_stripped",
                    "Raw HTML in the source was sanitized and reduced to its supported "
                    "formatting subset.",
                )
            )
            result.extend(_sanitize_raw_html(node.content))
        else:
            issues.append(
                ConversionIssue(
                    "unsupported_inline_dropped", f"A {node.type!r} inline element was dropped."
                )
            )
    return result


# --- DOCX --------------------------------------------------------------------


def _check_docx_entry_name(name: str) -> None:
    """The same traversal posture `app.content.transfer` applies to a native
    `.zip` import's entries — every entry is read by name via `zipfile`
    (`python-docx` never calls `extractall`, so nothing here is ever written
    to disk under an entry's own name), but a name is refused outright rather
    than trusted to be harmless just because nothing currently writes it out.
    """
    if name.startswith(("/", "\\")):
        raise DocumentImportRejected("unexpected_entry", f"Unexpected archive entry: {name!r}.")
    segments = re.split(r"[\\/]", name)
    if any(segment in ("..", ".") for segment in segments):
        raise DocumentImportRejected("unexpected_entry", f"Unexpected archive entry: {name!r}.")


def _check_docx_zip_safety(
    data: bytes, *, max_entries: int, max_compression_ratio: int, max_uncompressed_bytes: int
) -> None:
    """The same zip-bomb and path-traversal defenses
    `app.content.transfer.parse_export_archive` applies to a native `.zip`
    import — a `.docx` is a zip archive too, and `python-docx` does not
    defend against a hostile one.
    """
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as error:
        raise DocumentImportRejected(
            "bad_document", "This file could not be read as a Word document."
        ) from error

    with archive:
        infos = archive.infolist()
        if not infos:
            raise DocumentImportRejected("bad_document", "This .docx file is empty.")
        if len(infos) > max_entries:
            raise DocumentImportRejected(
                "too_many_entries",
                f"A .docx file may hold at most {max_entries} internal entries.",
                status_code=413,
            )

        declared_total = 0
        has_content_types = False
        for info in infos:
            if info.is_dir():
                continue
            _check_docx_entry_name(info.filename)
            declared_total += info.file_size
            if declared_total > max_uncompressed_bytes:
                raise DocumentImportRejected(
                    "archive_too_large",
                    "This .docx file expands to more data than is accepted.",
                    status_code=413,
                )
            if info.compress_size > 0:
                if info.file_size / info.compress_size > max_compression_ratio:
                    raise DocumentImportRejected(
                        "suspicious_compression_ratio",
                        "This .docx file's compression ratio is not accepted.",
                        status_code=413,
                    )
            elif info.file_size > 0:
                raise DocumentImportRejected(
                    "suspicious_compression_ratio",
                    "This .docx file's compression ratio is not accepted.",
                    status_code=413,
                )
            if info.filename == "[Content_Types].xml":
                has_content_types = True

        if not has_content_types:
            raise DocumentImportRejected(
                "unrecognised_format", "This file is not a Word document."
            )


def _check_word_main_part(data: bytes) -> None:
    """Refuse a `.docx`-named file that is actually an Excel or PowerPoint
    (or arbitrary) OOXML package. Matched against the same main-part string
    `app.content.uploads._sniff_ooxml` uses for attachments, kept as its own
    copy for the same reason `_ASSET_REFERENCE_ATTRIBUTES` is duplicated
    across `app.routes.content` and `app.routes.transfer`: it is a fact about
    the OOXML format, not shared state either module owns.
    """
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        try:
            info = archive.getinfo("[Content_Types].xml")
        except KeyError as error:
            raise DocumentImportRejected(
                "unrecognised_format", "This file is not a Word document."
            ) from error
        if info.file_size > _MAX_CONTENT_TYPES_BYTES:
            raise DocumentImportRejected(
                "unrecognised_format", "This file is not a Word document."
            )
        declared = archive.read(info).decode("utf-8", errors="replace")
    if f'"{_WORD_MAIN_PART}"' not in declared:
        raise DocumentImportRejected(
            "unrecognised_format",
            "This file is not a Word document. Only .docx Word documents are accepted.",
        )


def _iter_block_items(document: DocxDocument):
    """Paragraphs and tables in document order — python-docx's own
    `document.paragraphs`/`document.tables` each give one type only, losing
    the interleaving a real document has between them.
    """
    from docx.text.paragraph import Paragraph

    body = document.element.body
    for child in body.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, document)
        elif child.tag == qn("w:tbl"):
            yield Table(child, document)


def _docx_paragraph_heading_level(paragraph: Any) -> int | None:
    match = _HEADING_STYLE_RE.match((paragraph.style.name or "").strip())
    return int(match.group(1)) if match else None


def _docx_list_kind(paragraph: Any, issues: list[ConversionIssue]) -> str | None:
    style_name = paragraph.style.name or ""
    if style_name.startswith("List Bullet"):
        return "bullet"
    if style_name.startswith("List Number"):
        return "ordered"
    p_pr = paragraph._p.pPr
    if p_pr is not None and p_pr.numPr is not None:
        # A numbered paragraph under a style this converter cannot classify
        # (most commonly Word's generic "List Paragraph") — imported as a
        # bulleted list, noted once rather than per paragraph.
        _note_once(
            issues,
            "list_style_assumed_bullet",
            "A list used a style this import could not classify as bulleted or "
            "numbered; it was imported as a bulleted list.",
        )
        return "bullet"
    return None


def _extract_docx_image(
    drawing_el: Any,
    doc_part: Any,
    issues: list[ConversionIssue],
    extracted_images: list[ConvertedImage],
) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for blip in drawing_el.findall(".//" + qn("a:blip")):
        r_id = blip.get(qn("r:embed"))
        if not r_id:
            continue
        try:
            part = doc_part.related_parts[r_id]
            raw = part.blob
        except KeyError:
            _note_once(
                issues, "image_unavailable", "An embedded image could not be read and was dropped."
            )
            continue
        filename = str(part.partname).rsplit("/", 1)[-1] or f"image-{uuid.uuid4().hex}.png"
        try:
            sniffed = sniff_upload(raw, kind="image", filename=filename)
        except UploadRejected as rejection:
            issues.append(
                ConversionIssue(
                    "image_dropped",
                    f"An embedded image ({filename}) could not be imported: {rejection.message}",
                )
            )
            continue
        placeholder = f"docx-image:{uuid.uuid4().hex}"
        extracted_images.append(
            ConvertedImage(placeholder=placeholder, data=raw, filename=sniffed.filename)
        )
        blocks.append(_image(placeholder))
    return blocks


def _docx_runs_to_pm(
    paragraph: Any,
    doc_part: Any,
    issues: list[ConversionIssue],
    extracted_images: list[ConvertedImage],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """One paragraph's text and marks, plus any embedded images as trailing
    block nodes — `image` is a block node in the schema, so an image inline
    with text can never nest inside the paragraph that contains it.
    """
    inline_nodes: list[dict[str, Any]] = []
    image_blocks: list[dict[str, Any]] = []
    for item in paragraph.iter_inner_content():
        if isinstance(item, Hyperlink):
            text = item.text
            if not text:
                continue
            mark = _link_mark(item.address or "")
            if mark is None:
                _note_once(
                    issues,
                    "link_dropped",
                    "A link used an unsupported address and was kept as plain text.",
                )
                node = _text(text)
            else:
                node = _text(text, [mark])
            if node:
                inline_nodes.append(node)
            continue

        run = item
        drawings = run._element.findall(qn("w:drawing"))
        if drawings:
            for drawing in drawings:
                image_blocks.extend(_extract_docx_image(drawing, doc_part, issues, extracted_images))
            continue
        if run.text:
            marks: list[dict[str, Any]] = []
            if run.bold:
                marks.append({"type": "bold"})
            if run.italic:
                marks.append({"type": "italic"})
            node = _text(run.text, marks or None)
            if node:
                inline_nodes.append(node)
    return inline_nodes, image_blocks


def _docx_events(
    document: DocxDocument, issues: list[ConversionIssue]
) -> tuple[str | None, list[tuple[str, Any]], list[ConvertedImage]]:
    events: list[tuple[str, Any]] = []
    extracted_images: list[ConvertedImage] = []
    title: str | None = None
    first = True
    table_reported = False

    current_list_kind: str | None = None
    current_list_items: list[dict[str, Any]] = []

    def flush_list() -> None:
        nonlocal current_list_kind, current_list_items
        if current_list_items:
            node = (
                _bullet_list(current_list_items)
                if current_list_kind == "bullet"
                else _ordered_list(current_list_items)
            )
            if node is not None:
                events.append(("block", node))
        current_list_kind = None
        current_list_items = []

    for item in _iter_block_items(document):
        if isinstance(item, Table):
            flush_list()
            first = False
            if not table_reported:
                issues.append(
                    ConversionIssue(
                        "table_dropped",
                        "This document contains one or more tables; tables are not "
                        "supported and were dropped.",
                    )
                )
                table_reported = True
            continue

        paragraph = item
        heading_level = _docx_paragraph_heading_level(paragraph)

        if heading_level == 1 and first:
            flush_list()
            inline_nodes, image_blocks = _docx_runs_to_pm(
                paragraph, document.part, issues, extracted_images
            )
            title = _plain_text(inline_nodes).strip() or None
            events.extend(("block", block) for block in image_blocks)
            first = False
            continue
        first = False

        if heading_level == 2:
            flush_list()
            inline_nodes, image_blocks = _docx_runs_to_pm(
                paragraph, document.part, issues, extracted_images
            )
            events.append(("page_break", _plain_text(inline_nodes).strip()))
            events.extend(("block", block) for block in image_blocks)
            continue

        list_kind = _docx_list_kind(paragraph, issues)
        if list_kind is not None:
            if current_list_kind is not None and current_list_kind != list_kind:
                flush_list()
            current_list_kind = list_kind
            inline_nodes, image_blocks = _docx_runs_to_pm(
                paragraph, document.part, issues, extracted_images
            )
            current_list_items.append(_list_item([_paragraph(inline_nodes)]))
            if image_blocks:
                flush_list()
                events.extend(("block", block) for block in image_blocks)
            continue

        flush_list()
        inline_nodes, image_blocks = _docx_runs_to_pm(
            paragraph, document.part, issues, extracted_images
        )
        if heading_level is not None:
            clamped = _clamp_heading_level(heading_level, issues)
            block = _heading(clamped, inline_nodes)
        else:
            block = _paragraph(inline_nodes)
        if block is not None:
            events.append(("block", block))
        events.extend(("block", image_block) for image_block in image_blocks)

    flush_list()
    return title, events, extracted_images


def convert_docx(
    data: bytes,
    *,
    filename: str,
    max_entries: int,
    max_compression_ratio: int,
    max_uncompressed_bytes: int,
) -> ConvertedDocument:
    _check_docx_zip_safety(
        data,
        max_entries=max_entries,
        max_compression_ratio=max_compression_ratio,
        max_uncompressed_bytes=max_uncompressed_bytes,
    )
    _check_word_main_part(data)

    try:
        document = DocxDocument(io.BytesIO(data))
    except Exception as error:  # python-docx raises a mix of exception types
        raise DocumentImportRejected(
            "bad_document", "This file could not be read as a Word document."
        ) from error

    issues: list[ConversionIssue] = []
    extracted_title, events, images = _docx_events(document, issues)
    module_title = _clamp_title(extracted_title, issues, fallback=_title_from_filename(filename))
    if extracted_title is None:
        issues.append(
            ConversionIssue(
                "title_inferred_from_filename",
                "No top-level heading was found; the module title was taken from the file name.",
            )
        )

    pages = _finalize_pages(_group_sections(events), issues, module_title=module_title)
    _enforce_page_count(pages)

    converted_pages = [
        ConvertedPage(title=title, body={"type": "doc", "content": blocks})
        for title, blocks in pages
    ]
    return ConvertedDocument(title=module_title, pages=converted_pages, images=images, issues=issues)


# --- PDF -----------------------------------------------------------------


def _split_pdf_paragraphs(text: str) -> list[str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    result: list[str] = []
    for raw_paragraph in re.split(r"\n\s*\n", normalized):
        collapsed = " ".join(line.strip() for line in raw_paragraph.split("\n") if line.strip())
        if collapsed:
            result.append(collapsed)
    return result


def convert_pdf(data: bytes, *, filename: str) -> ConvertedDocument:
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise DocumentImportRejected(
                "encrypted_pdf", "Password-protected PDFs cannot be imported."
            )
        page_count = len(reader.pages)
    except DocumentImportRejected:
        raise
    except (PdfReadError, ValueError, KeyError) as error:
        raise DocumentImportRejected(
            "bad_document", "This file could not be read as a PDF."
        ) from error

    issues: list[ConversionIssue] = [
        ConversionIssue(
            "pdf_best_effort",
            "PDF import extracts text only; layout, images, tables, and formatting "
            "are not preserved.",
        )
    ]

    title: str | None = None
    try:
        if reader.metadata is not None and reader.metadata.title:
            title = reader.metadata.title.strip() or None
    except (PdfReadError, KeyError, ValueError, TypeError):
        title = None
    module_title = _clamp_title(title, issues, fallback=_title_from_filename(filename))
    if title is None:
        issues.append(
            ConversionIssue(
                "title_inferred_from_filename",
                "This PDF has no title in its metadata; the module title was taken "
                "from the file name.",
            )
        )

    pages: list[tuple[str, list[dict[str, Any]]]] = []
    for index in range(page_count):
        try:
            text = reader.pages[index].extract_text() or ""
        except (PdfReadError, KeyError, ValueError, TypeError):
            text = ""
            issues.append(
                ConversionIssue(
                    "page_extraction_failed",
                    f"Page {index + 1} could not be read and was imported as blank.",
                )
            )
        blocks = [_paragraph([_text(paragraph)]) for paragraph in _split_pdf_paragraphs(text)]
        blocks = [block for block in blocks if block is not None]
        if not blocks:
            issues.append(
                ConversionIssue(
                    "empty_page_dropped",
                    f"Page {index + 1} had no extractable text and was dropped.",
                )
            )
            continue
        pages.append((f"Page {index + 1}", blocks))

    _enforce_page_count(pages)

    converted_pages = [
        ConvertedPage(title=title, body={"type": "doc", "content": blocks})
        for title, blocks in pages
    ]
    return ConvertedDocument(title=module_title, pages=converted_pages, issues=issues)


# --- Dispatch ------------------------------------------------------------


def convert_document(
    fmt: DocumentFormat,
    data: bytes,
    *,
    filename: str,
    docx_max_entries: int,
    docx_max_compression_ratio: int,
    docx_max_uncompressed_bytes: int,
) -> ConvertedDocument:
    if fmt == "markdown":
        return convert_markdown(data, filename=filename)
    if fmt == "docx":
        return convert_docx(
            data,
            filename=filename,
            max_entries=docx_max_entries,
            max_compression_ratio=docx_max_compression_ratio,
            max_uncompressed_bytes=docx_max_uncompressed_bytes,
        )
    if fmt == "pdf":
        return convert_pdf(data, filename=filename)
    raise DocumentImportRejected("unrecognised_format", f"Unknown document format: {fmt!r}.")
