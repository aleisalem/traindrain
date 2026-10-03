"""The `module.json` manifest carried inside a native export archive.

`ModuleExportDocument` is the single source of truth for what a `.zip` export
contains — the same schema both writes an export and parses one back in, so
the two directions of the round trip can never quietly disagree about shape.
`extra="forbid"` throughout: an archive carrying a field this schema does not
know about is rejected, not silently ignored.
"""

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.schemas.modules import AssetKind, ModuleLanguage

# Versioned so a future, incompatible export shape can be told apart from this
# one rather than misread as it. There is exactly one version today.
EXPORT_FORMAT: Literal["traindrain.module/1"] = "traindrain.module/1"


class ExportedPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    schema_version: int
    # Validated again on import through the same server-side ProseMirror
    # validator every authored page goes through — this schema only checks
    # that a body is present, never that it conforms.
    body: dict[str, Any]


class ExportedAsset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    kind: AssetKind
    # Informational only: what the *original* upload sniffed as and how large
    # it was. Neither is trusted on import — the re-extracted bytes are
    # sniffed and sized again from scratch, exactly as a fresh upload is.
    content_type: str
    original_filename: str
    size_bytes: int


class ModuleExportDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format: Literal["traindrain.module/1"]
    title: str
    description: str | None = None
    language: ModuleLanguage
    estimated_duration_minutes: int | None = None
    pages: list[ExportedPage]
    assets: list[ExportedAsset]
