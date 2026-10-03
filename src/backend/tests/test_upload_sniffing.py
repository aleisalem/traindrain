"""The upload sniffer, exercised directly.

This is the control that decides what bytes are allowed to enter the platform,
so it gets tested as a unit as well as through the route: every rejection here
is a rejection, never a strip-and-accept, and the declared kind never wins over
what the bytes actually say.
"""

import io
import zipfile

import pytest

from app.content.uploads import UploadRejected, sniff_upload

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
GIF = b"GIF89a" + b"\x00" * 32
WEBP = b"RIFF" + b"\x24\x00\x00\x00" + b"WEBP" + b"VP8 " + b"\x00" * 16
PDF = b"%PDF-1.7\n" + b"trailer\n" + b"\x00" * 16

_OOXML_MAIN_PARTS = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml",
}


def ooxml(main_part: str, *, extra: dict[str, bytes] | None = None) -> bytes:
    """A minimal OOXML package declaring `main_part` in `[Content_Types].xml`."""
    buffer = io.BytesIO()
    content_types = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        f'<Override PartName="/word/document.xml" ContentType="{main_part}"/>'
        "</Types>"
    ).encode()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("word/document.xml", b"<document/>")
        for name, payload in (extra or {}).items():
            archive.writestr(name, payload)
    return buffer.getvalue()


# --- The allowed set ------------------------------------------------------


@pytest.mark.parametrize(
    ("data", "filename", "expected"),
    [
        (PNG, "diagram.png", "image/png"),
        (JPEG, "photo.jpg", "image/jpeg"),
        (JPEG, "photo.jpeg", "image/jpeg"),
        (GIF, "anim.gif", "image/gif"),
        (WEBP, "shot.webp", "image/webp"),
    ],
)
def test_an_allowed_image_is_accepted(data: bytes, filename: str, expected: str) -> None:
    result = sniff_upload(data, kind="image", filename=filename)

    assert result.content_type == expected
    assert result.filename == filename


@pytest.mark.parametrize(
    ("data", "filename", "expected"),
    [
        (PDF, "policy.pdf", "application/pdf"),
        (
            ooxml(_OOXML_MAIN_PARTS["docx"]),
            "handbook.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
        (
            ooxml(_OOXML_MAIN_PARTS["xlsx"]),
            "register.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
        (
            ooxml(_OOXML_MAIN_PARTS["pptx"]),
            "deck.pptx",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ),
        (b"a checklist\nline two\n", "checklist.txt", "text/plain; charset=utf-8"),
        (b"name,role\nAnna,Lead\n", "roster.csv", "text/plain; charset=utf-8"),
    ],
)
def test_an_allowed_attachment_is_accepted(data: bytes, filename: str, expected: str) -> None:
    result = sniff_upload(data, kind="attachment", filename=filename)

    assert result.content_type == expected


def test_a_utf8_text_attachment_with_a_bom_is_accepted() -> None:
    result = sniff_upload("\ufeffname,rôle\n".encode(), kind="attachment", filename="r.csv")

    assert result.content_type == "text/plain; charset=utf-8"


# --- SVG, specifically ----------------------------------------------------


@pytest.mark.parametrize(
    "data",
    [
        b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
        b'<?xml version="1.0"?>\n<svg xmlns="http://www.w3.org/2000/svg"/>',
        b"\n\n  <SVG onload=\"alert(1)\"/>",
    ],
)
def test_svg_is_rejected_outright(data: bytes) -> None:
    """Not "unrecognised" — named, so the author is told why."""
    with pytest.raises(UploadRejected) as rejection:
        sniff_upload(data, kind="image", filename="logo.svg")

    assert rejection.value.code == "svg_not_allowed"


def test_svg_is_rejected_as_an_attachment_too() -> None:
    with pytest.raises(UploadRejected) as rejection:
        sniff_upload(b"<svg/>", kind="attachment", filename="logo.svg")

    assert rejection.value.code == "svg_not_allowed"


def test_an_svg_renamed_to_png_is_still_rejected() -> None:
    with pytest.raises(UploadRejected) as rejection:
        sniff_upload(b"<svg/>", kind="image", filename="innocent.png")

    assert rejection.value.code == "svg_not_allowed"


# --- The bytes win over what the client claims ----------------------------


def test_a_pdf_declared_as_an_image_is_rejected() -> None:
    """The declared kind does not get to relabel the bytes."""
    with pytest.raises(UploadRejected) as rejection:
        sniff_upload(PDF, kind="image", filename="policy.png")

    assert rejection.value.code == "unrecognised_image"


def test_an_image_declared_as_an_attachment_is_rejected() -> None:
    with pytest.raises(UploadRejected) as rejection:
        sniff_upload(PNG, kind="attachment", filename="diagram.pdf")

    assert rejection.value.code == "unrecognised_attachment"


def test_an_extension_that_contradicts_the_sniffed_type_is_rejected() -> None:
    """A real PNG named `.jpg`: both checks have to agree, not just one."""
    with pytest.raises(UploadRejected) as rejection:
        sniff_upload(PNG, kind="image", filename="diagram.jpg")

    assert rejection.value.code == "extension_mismatch"


@pytest.mark.parametrize(
    "data",
    [
        b"MZ\x90\x00\x03" + b"\x00" * 32,  # a Windows executable
        b"\x7fELF\x02\x01\x01" + b"\x00" * 32,  # an ELF binary
        b"#!/bin/sh\nrm -rf /\n",  # a shell script
        b"\x1f\x8b\x08\x00" + b"\x00" * 32,  # gzip
    ],
)
def test_an_executable_or_archive_is_never_an_image(data: bytes) -> None:
    with pytest.raises(UploadRejected):
        sniff_upload(data, kind="image", filename="payload.png")


def test_a_plain_zip_is_not_an_ooxml_attachment() -> None:
    """`PK` alone is not enough — the OOXML content-types part has to be there."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("payload.exe", b"MZ\x90\x00")

    with pytest.raises(UploadRejected) as rejection:
        sniff_upload(buffer.getvalue(), kind="attachment", filename="bundle.docx")

    assert rejection.value.code == "unrecognised_attachment"


def test_a_macro_enabled_document_is_rejected() -> None:
    """`.docm` is a macro carrier; only the non-macro main part is allowlisted."""
    macro_part = (
        "application/vnd.ms-word.document.macroEnabled.main+xml"
    )

    with pytest.raises(UploadRejected) as rejection:
        sniff_upload(ooxml(macro_part), kind="attachment", filename="handbook.docx")

    assert rejection.value.code == "unrecognised_attachment"


def test_an_xlsx_renamed_to_docx_is_rejected() -> None:
    with pytest.raises(UploadRejected) as rejection:
        sniff_upload(ooxml(_OOXML_MAIN_PARTS["xlsx"]), kind="attachment", filename="book.docx")

    assert rejection.value.code == "extension_mismatch"


# --- Text that is not really text -----------------------------------------


def test_html_uploaded_as_text_is_rejected() -> None:
    """Refused even though it decodes cleanly: an HTML file is not a checklist."""
    with pytest.raises(UploadRejected) as rejection:
        sniff_upload(b"<html><script>alert(1)</script></html>", kind="attachment", filename="a.txt")

    assert rejection.value.code == "unrecognised_attachment"


@pytest.mark.parametrize(
    "data",
    [
        b"line one\x00line two",  # a NUL byte
        b"line one\x1bline two",  # an ANSI escape
        b"\xff\xfe\x00h\x00i",  # UTF-16, which is not what we accept
    ],
)
def test_binary_masquerading_as_text_is_rejected(data: bytes) -> None:
    with pytest.raises(UploadRejected):
        sniff_upload(data, kind="attachment", filename="notes.txt")


# --- Filenames ------------------------------------------------------------


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("../../etc/passwd.png", "passwd.png"),
        (r"C:\Users\anna\diagram.png", "diagram.png"),
        ("/tmp/diagram.png", "diagram.png"),
    ],
)
def test_a_path_in_the_filename_is_reduced_to_its_basename(
    filename: str, expected: str
) -> None:
    """The stored name is echoed in a download header; it is never a path."""
    result = sniff_upload(PNG, kind="image", filename=filename)

    assert result.filename == expected


def test_a_newline_in_the_filename_is_rejected() -> None:
    """Header injection: the name reaches a `Content-Disposition` value."""
    with pytest.raises(UploadRejected) as rejection:
        sniff_upload(PNG, kind="image", filename="diagram.png\r\nX-Evil: 1")

    assert rejection.value.code == "bad_filename"


def test_an_overlong_filename_is_rejected() -> None:
    with pytest.raises(UploadRejected) as rejection:
        sniff_upload(PNG, kind="image", filename="a" * 300 + ".png")

    assert rejection.value.code == "bad_filename"


def test_a_filename_with_no_extension_is_rejected() -> None:
    with pytest.raises(UploadRejected) as rejection:
        sniff_upload(PNG, kind="image", filename="diagram")

    assert rejection.value.code == "extension_mismatch"


def test_a_double_extension_is_judged_on_its_last_one() -> None:
    with pytest.raises(UploadRejected) as rejection:
        sniff_upload(PNG, kind="image", filename="diagram.png.exe")

    assert rejection.value.code == "extension_mismatch"


# --- Degenerate input -----------------------------------------------------


def test_an_empty_file_is_rejected() -> None:
    with pytest.raises(UploadRejected) as rejection:
        sniff_upload(b"", kind="image", filename="empty.png")

    assert rejection.value.code == "empty_file"


def test_an_unknown_kind_is_rejected() -> None:
    with pytest.raises(UploadRejected) as rejection:
        sniff_upload(PNG, kind="video", filename="clip.png")

    assert rejection.value.code == "unknown_kind"
