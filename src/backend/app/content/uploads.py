"""What an uploaded file has to be before it is allowed into the platform.

The same posture as `app.content.validation`: an upload that does not conform
is **rejected, never repaired and accepted**. Nothing here strips a byte and
stores the remainder.

The client's declared content type is not consulted at all — a browser will
happily send whatever `Content-Type` the file picker guessed, and an attacker
sends whatever they like. What a file *is* comes from its bytes; the filename
extension is then required to agree with them, so both the bytes and the name
have to be honest rather than either one alone.

Deliberately hand-rolled over libmagic or a detection package: the allowlist is
six document types and four image types, the checks fit on a screen, and a
control on this path is worth reading in full rather than trusting a
third-party heuristic whose output would have to be mapped onto this allowlist
anyway.
"""

import io
import re
import zipfile
from dataclasses import dataclass

KINDS = ("image", "attachment")

# Canonical content type -> the filename extensions that may carry it. Both the
# sniffed type and the extension have to land in the same row.
IMAGE_EXTENSIONS: dict[str, frozenset[str]] = {
    "image/png": frozenset({"png"}),
    "image/jpeg": frozenset({"jpg", "jpeg"}),
    "image/gif": frozenset({"gif"}),
    "image/webp": frozenset({"webp"}),
}

_OOXML_WORD = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_OOXML_EXCEL = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_OOXML_POWERPOINT = "application/vnd.openxmlformats-officedocument.presentationml.presentation"

ATTACHMENT_EXTENSIONS: dict[str, frozenset[str]] = {
    "application/pdf": frozenset({"pdf"}),
    _OOXML_WORD: frozenset({"docx"}),
    _OOXML_EXCEL: frozenset({"xlsx"}),
    _OOXML_POWERPOINT: frozenset({"pptx"}),
    # `.txt` and `.csv` are one sniffed type: both are UTF-8 text, and the
    # distinction between them is a convention about commas, not something the
    # bytes can be asked. Both are served as a download either way, so the
    # narrower label buys nothing and would only be a claim we cannot check.
    "text/plain; charset=utf-8": frozenset({"txt", "csv"}),
}

EXTENSIONS_BY_KIND: dict[str, dict[str, frozenset[str]]] = {
    "image": IMAGE_EXTENSIONS,
    "attachment": ATTACHMENT_EXTENSIONS,
}

# The OOXML main document part each format declares in `[Content_Types].xml`.
# Matched exactly, which is what keeps the macro-enabled formats out: a `.docm`
# declares `...wordprocessingml.document.macroEnabled.main+xml`, a different
# string, and a macro carrier is not something this platform stores.
_OOXML_MAIN_PARTS: dict[str, str] = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml": (
        _OOXML_WORD
    ),
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml": _OOXML_EXCEL,
    "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml": (
        _OOXML_POWERPOINT
    ),
}

MAX_FILENAME_LENGTH = 200

# Read only what the signature checks need; the rest of the file is never
# inspected, and never has to be held in memory to be judged.
_SNIFF_WINDOW = 1024

# How much of an OOXML package's content-types part is read before giving up.
# A legitimate one is a few kilobytes; the cap is what stops a crafted archive
# from expanding a tiny entry into memory.
_MAX_CONTENT_TYPES_BYTES = 512 * 1024
_MAX_ZIP_ENTRIES = 2048

# Control characters have no business in a name that ends up in a
# `Content-Disposition` header, and CR/LF there is header injection.
_FILENAME_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")

# Anything outside this is not the plain text we accept. Tab, newline and
# carriage return are the only control characters a checklist legitimately has.
_TEXT_CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class UploadRejected(Exception):
    """An upload that may not be stored. Always a 4xx, never a repair."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class SniffedUpload:
    """What the bytes turned out to be, and the name they may be stored under."""

    content_type: str
    filename: str


def sniff_upload(data: bytes, *, kind: str, filename: str) -> SniffedUpload:
    """Decide what `data` actually is, or refuse it.

    `kind` is what the author says they are adding — an illustration or a
    downloadable file. It narrows which allowlist applies; it never relabels
    the bytes.
    """
    if kind not in KINDS:
        raise UploadRejected("unknown_kind", f"An asset is an image or an attachment, not {kind!r}.")
    if not data:
        raise UploadRejected("empty_file", "An empty file cannot be stored.")

    # Checked before either allowlist, and for both kinds, so an SVG gets told
    # why it was refused rather than falling out as "unrecognised". SVG is a
    # full scripting host wearing an image's file extension.
    _reject_svg(data)

    content_type = (
        _sniff_image(data) if kind == "image" else _sniff_attachment(data)
    )
    stored_name = _check_filename(filename, kind=kind, content_type=content_type)
    return SniffedUpload(content_type=content_type, filename=stored_name)


def _reject_svg(data: bytes) -> None:
    head = data[:_SNIFF_WINDOW].lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    if head.startswith(b"<svg") or (head.startswith(b"<?xml") and b"<svg" in head):
        raise UploadRejected(
            "svg_not_allowed",
            "SVG files can carry scripts and are not accepted. Use PNG, JPEG, WebP, or GIF.",
        )


def _sniff_image(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    # A WebP file is a RIFF container whose form type, at offset 8, is `WEBP`.
    # The four bytes between are the chunk length, which is not checked here.
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    raise UploadRejected(
        "unrecognised_image",
        "This file is not a PNG, JPEG, WebP, or GIF image.",
    )


def _sniff_attachment(data: bytes) -> str:
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    if data.startswith(b"PK\x03\x04"):
        return _sniff_ooxml(data)
    return _sniff_text(data)


def _sniff_ooxml(data: bytes) -> str:
    """A ZIP is only an attachment if it is one of the three Office formats.

    `PK` on its own says nothing — a renamed `.jar`, an installer, and a
    `.docx` all start with it. What distinguishes them is the OOXML package's
    `[Content_Types].xml` declaring a main document part.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            if len(entries) > _MAX_ZIP_ENTRIES:
                raise UploadRejected(
                    "unrecognised_attachment",
                    "This archive holds more entries than an Office document ever does.",
                )
            content_types = next(
                (entry for entry in entries if entry.filename == "[Content_Types].xml"), None
            )
            if content_types is None or content_types.file_size > _MAX_CONTENT_TYPES_BYTES:
                raise UploadRejected(
                    "unrecognised_attachment",
                    "This file is not a Word, Excel, or PowerPoint document.",
                )
            with archive.open(content_types) as part:
                declared = part.read(_MAX_CONTENT_TYPES_BYTES).decode("utf-8", errors="replace")
    except UploadRejected:
        raise
    except (zipfile.BadZipFile, OSError, ValueError) as error:
        raise UploadRejected(
            "unrecognised_attachment", "This file could not be read as an Office document."
        ) from error

    for main_part, content_type in _OOXML_MAIN_PARTS.items():
        if f'"{main_part}"' in declared:
            return content_type
    raise UploadRejected(
        "unrecognised_attachment",
        "This file is not a Word, Excel, or PowerPoint document. "
        "Macro-enabled documents are not accepted.",
    )


def _sniff_text(data: bytes) -> str:
    """UTF-8 text, and text that is genuinely text.

    A file that decodes cleanly can still be markup — and a stored `.txt` that
    is really HTML is a stored page waiting for a content-type mistake to
    render it. Refused here rather than relied on being served safely.
    """
    try:
        decoded = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise UploadRejected(
            "unrecognised_attachment",
            "This file is not one of the accepted document types "
            "(PDF, Word, Excel, PowerPoint, or UTF-8 text).",
        ) from error

    if _TEXT_CONTROL_CHARACTERS.search(decoded):
        raise UploadRejected(
            "unrecognised_attachment",
            "This file looks like binary data rather than text.",
        )
    if decoded.lstrip("﻿ \t\r\n").startswith("<"):
        raise UploadRejected(
            "unrecognised_attachment",
            "Markup files are not accepted as attachments.",
        )
    return "text/plain; charset=utf-8"


def _check_filename(filename: str, *, kind: str, content_type: str) -> str:
    """Reduce a submitted name to a safe basename whose extension agrees with the bytes."""
    if _FILENAME_CONTROL_CHARACTERS.search(filename):
        raise UploadRejected(
            "bad_filename", "A file name may not contain control characters or line breaks."
        )

    # Both separators, whatever the uploading platform: a Windows client sends
    # backslashes, and `PurePosixPath` would keep them as part of the name.
    basename = re.split(r"[\\/]", filename)[-1].strip()
    if basename in {"", ".", ".."}:
        raise UploadRejected("bad_filename", "This file needs a name.")
    if len(basename) > MAX_FILENAME_LENGTH:
        raise UploadRejected(
            "bad_filename", f"A file name may be at most {MAX_FILENAME_LENGTH} characters."
        )

    # The *last* extension decides, so `report.pdf.exe` is judged on `.exe`.
    _, _, extension = basename.rpartition(".")
    allowed = EXTENSIONS_BY_KIND[kind][content_type]
    if extension.lower() not in allowed:
        raise UploadRejected(
            "extension_mismatch",
            f"This file's contents are {content_type}, so its name must end in "
            f"{' or '.join('.' + suffix for suffix in sorted(allowed))}.",
        )
    return basename
