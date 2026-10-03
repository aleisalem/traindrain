"""Building and parsing the native `.zip` export/import archive.

The same posture as `app.content.uploads` and `app.content.validation`: an
archive that does not conform to the expected shape is **rejected outright**,
never repaired and accepted. There is no `extractall` anywhere in this module
— every entry is identified by matching its name against a strict allowlist
and read individually, so a hostile name can never be written anywhere on
disk, and a hostile entry can never be read under any name but the one this
module decided it must have.

Two independent defenses against a zip bomb: the archive's own declared
metadata (entry count, per-entry compression ratio) is checked before any
entry is decompressed, and every actual read is bounded by a shared byte
budget that does not trust that metadata — an entry whose *true* decompressed
size disagrees with what it claims about itself still cannot exceed the
budget, because the read that would prove it is capped at the budget's size.
"""

import io
import json
import re
import zipfile
from dataclasses import dataclass
from uuid import UUID

from pydantic import ValidationError

from app.schemas.transfer import ExportedAsset, ModuleExportDocument

MODULE_JSON_ENTRY = "module.json"

# `assets/<uuid>/<basename>` — the only other shape an entry may take. The
# basename excludes `/`, `\`, and control characters, and the pattern is
# matched with `fullmatch`, so there is no third path segment for `..` to
# hide in and no way for a name to mean two different things depending on
# what reads it.
_ASSET_ENTRY_PATTERN = re.compile(
    r"^assets/(?P<asset_id>[0-9a-fA-F-]{36})/(?P<filename>[^/\\\x00-\x1f]{1,200})$"
)


class ArchiveRejected(Exception):
    """An import archive that may not be processed. Always a 4xx, never a repair."""

    def __init__(self, code: str, message: str, *, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def asset_zip_path(asset_id: UUID, filename: str) -> str:
    return f"assets/{asset_id}/{filename}"


def build_export_archive(
    document: ModuleExportDocument, asset_bytes: dict[UUID, bytes]
) -> bytes:
    """Serialize a module export to `.zip` bytes: `module.json` plus its assets."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(MODULE_JSON_ENTRY, document.model_dump_json())
        for asset in document.assets:
            archive.writestr(
                asset_zip_path(asset.id, asset.original_filename), asset_bytes[asset.id]
            )
    return buffer.getvalue()


@dataclass(frozen=True)
class ParsedArchive:
    document: ModuleExportDocument
    asset_bytes: dict[UUID, bytes]


def parse_export_archive(
    data: bytes,
    *,
    max_entries: int,
    max_compression_ratio: int,
    max_uncompressed_bytes: int,
) -> ParsedArchive:
    """Validate and unpack an uploaded archive, or raise `ArchiveRejected`.

    Every entry is checked against the allowlist and the size/ratio caps
    *before* any entry's bytes are read, so a hostile archive is refused
    without ever decompressing the part that would make it hostile.
    """
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as error:
        raise ArchiveRejected(
            "bad_archive", "This file is not a valid .zip archive."
        ) from error

    with archive:
        infos = archive.infolist()
        if not infos:
            raise ArchiveRejected("empty_archive", "This archive is empty.")
        if len(infos) > max_entries:
            raise ArchiveRejected(
                "too_many_entries",
                f"An archive may hold at most {max_entries} entries.",
                status_code=413,
            )

        module_json_info: zipfile.ZipInfo | None = None
        asset_infos: dict[UUID, zipfile.ZipInfo] = {}
        declared_total = 0

        for info in infos:
            name = info.filename
            if info.is_dir():
                raise ArchiveRejected(
                    "unexpected_entry", f"Unexpected directory entry: {name!r}."
                )

            declared_total += info.file_size
            if declared_total > max_uncompressed_bytes:
                raise ArchiveRejected(
                    "archive_too_large",
                    "This archive expands to more data than is accepted.",
                    status_code=413,
                )
            if info.compress_size > 0:
                if info.file_size / info.compress_size > max_compression_ratio:
                    raise ArchiveRejected(
                        "suspicious_compression_ratio",
                        "This archive's compression ratio is not accepted.",
                        status_code=413,
                    )
            elif info.file_size > 0:
                # A non-empty entry that claims to compress to nothing is not
                # a shape a real file takes — refuse rather than decompress it
                # to find out.
                raise ArchiveRejected(
                    "suspicious_compression_ratio",
                    "This archive's compression ratio is not accepted.",
                    status_code=413,
                )

            if name == MODULE_JSON_ENTRY:
                module_json_info = info
                continue

            match = _ASSET_ENTRY_PATTERN.fullmatch(name)
            if match is None:
                raise ArchiveRejected("unexpected_entry", f"Unexpected archive entry: {name!r}.")
            try:
                asset_id = UUID(match.group("asset_id"))
            except ValueError as error:
                raise ArchiveRejected(
                    "unexpected_entry", f"Unexpected archive entry: {name!r}."
                ) from error
            if asset_id in asset_infos:
                raise ArchiveRejected(
                    "duplicate_entry", f"Duplicate archive entry for asset {asset_id}."
                )
            asset_infos[asset_id] = info

        if module_json_info is None:
            raise ArchiveRejected("missing_module_json", "This archive has no module.json.")

        # The real bomb defense: a bounded read that does not trust
        # `info.file_size`. `budget` is shared across every entry read below,
        # so no combination of entries — however their own metadata lies —
        # can make this function hold more than `max_uncompressed_bytes` of
        # decompressed data in memory at once.
        budget = max_uncompressed_bytes

        def _read_bounded(info: zipfile.ZipInfo) -> bytes:
            nonlocal budget
            with archive.open(info) as stream:
                chunk = stream.read(budget + 1)
            if len(chunk) > budget:
                raise ArchiveRejected(
                    "archive_too_large",
                    "This archive expands to more data than is accepted.",
                    status_code=413,
                )
            budget -= len(chunk)
            return chunk

        try:
            manifest = json.loads(_read_bounded(module_json_info).decode("utf-8"))
        except UnicodeDecodeError as error:
            raise ArchiveRejected(
                "invalid_module_json", "module.json is not valid UTF-8."
            ) from error
        except json.JSONDecodeError as error:
            raise ArchiveRejected(
                "invalid_module_json", "module.json is not valid JSON."
            ) from error

        try:
            document = ModuleExportDocument.model_validate(manifest)
        except ValidationError as error:
            raise ArchiveRejected(
                "invalid_module_json",
                f"module.json does not match the export format: {error}",
            ) from error

        _check_assets_match(document.assets, asset_infos)

        asset_bytes = {
            asset_id: _read_bounded(info) for asset_id, info in asset_infos.items()
        }

    return ParsedArchive(document=document, asset_bytes=asset_bytes)


def _check_assets_match(
    assets: list[ExportedAsset], asset_infos: dict[UUID, zipfile.ZipInfo]
) -> None:
    declared_ids = {asset.id for asset in assets}
    if len(declared_ids) != len(assets):
        raise ArchiveRejected(
            "duplicate_asset_id", "module.json declares the same asset id twice."
        )
    if declared_ids != set(asset_infos):
        raise ArchiveRejected(
            "asset_mismatch",
            "The assets declared in module.json do not match the files in the archive.",
        )
    for asset in assets:
        actual_filename = asset_infos[asset.id].filename.rsplit("/", 1)[-1]
        if actual_filename != asset.original_filename:
            raise ArchiveRejected(
                "asset_mismatch",
                f"Asset {asset.id} is declared under a different filename than its entry.",
            )
