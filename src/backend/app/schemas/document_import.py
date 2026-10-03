"""The response to a document-import upload: the created draft, plus its report.

Conversion is lossy by nature (see `app.content.document_import`), so the
response is never just the module — an author who does not see what was
dropped or altered has no way to know where to look for damage.
"""

from pydantic import BaseModel, ConfigDict

from app.schemas.modules import ModuleResponse


class ConversionReportEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str


class DocumentImportResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    module: ModuleResponse
    conversion_report: list[ConversionReportEntry]
