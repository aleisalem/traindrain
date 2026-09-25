"""Document import: Markdown, DOCX, and PDF, converted into a fresh draft module.

Existing written material becomes training content without being retyped by
hand. `app.content.document_import` does the lossy work of turning a file
into page trees and a list of what it had to drop or alter; this route is
what makes that trustworthy enough to store — every converted page goes
through `app.routes.content.validate_page_body`, the exact same server-side
ProseMirror validator authored content goes through, and every embedded image
goes through `app.content.uploads.sniff_upload`, the exact same byte-level
sniffing a fresh asset upload goes through. Arriving from a converter earns a
document no shortcut past either check.

An import always lands as a fresh, unpublished draft in its own new
translation group — there is no import-and-publish path, matching
`app.routes.transfer.import_module`.
"""

import logging
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.content import SCHEMA_VERSION, TEXT_SEARCH_CONFIGS
from app.content.document_import import (
    ConversionIssue,
    ConvertedDocument,
    ConvertedImage,
    DocumentImportRejected,
    convert_document,
    sniff_document_format,
)
from app.content.uploads import UploadRejected, sniff_upload
from app.core.config import get_settings
from app.db import get_db
from app.dependencies import get_s3_client, require_content_manager
from app.models import Module, ModuleAsset, ModulePage, ModuleTranslationGroup, User
from app.routes.assets import asset_url, read_upload_within_cap
from app.routes.content import module_response, validate_page_body
from app.schemas.document_import import ConversionReportEntry, DocumentImportResponse
from app.schemas.modules import ModuleLanguage
from app.security.audit import record_audit_log
from app.storage import S3Client, delete_asset, object_key, put_asset

router = APIRouter(prefix="/api/content", tags=["content"])

logger = logging.getLogger(__name__)


def _document_import_error(rejection: DocumentImportRejected) -> HTTPException:
    return HTTPException(
        status_code=rejection.status_code,
        detail={"code": rejection.code, "message": rejection.message},
    )


def _rewrite_image_placeholders(value: Any, urls_by_placeholder: dict[str, str | None]) -> Any:
    """Repoint every `image` node's placeholder `src` at its real asset URL.

    A placeholder mapped to `None` (its upload was rejected — oversized, or a
    format `sniff_upload` refuses) means the image node itself is dropped
    rather than stored with a `src` the schema would reject.
    """
    if isinstance(value, dict):
        if value.get("type") == "image":
            attrs = value.get("attrs") or {}
            placeholder = attrs.get("src")
            if placeholder in urls_by_placeholder:
                url = urls_by_placeholder[placeholder]
                if url is None:
                    return None
                return {**value, "attrs": {**attrs, "src": url}}
            return value
        return {
            key: _rewrite_image_placeholders(item, urls_by_placeholder)
            for key, item in value.items()
        }
    if isinstance(value, list):
        rewritten = [_rewrite_image_placeholders(item, urls_by_placeholder) for item in value]
        return [item for item in rewritten if item is not None]
    return value


def _drop_empty_pages(
    pages: list[tuple[str, dict[str, Any]]], issues: list[ConversionIssue]
) -> list[tuple[str, dict[str, Any]]]:
    """After rewriting, a page whose only content was a rejected image is an
    empty `doc` — invalid (`doc` needs `block+`). Filled with a placeholder
    paragraph rather than dropped outright, so the page (and its title) the
    author is expecting still exists to be corrected by hand.
    """
    result: list[tuple[str, dict[str, Any]]] = []
    for title, body in pages:
        content = body.get("content") or []
        if not content:
            issues.append(
                ConversionIssue(
                    "page_left_blank",
                    f"The page {title!r} had no content left after a dropped image and "
                    "was imported blank.",
                )
            )
            body = {**body, "content": [{"type": "paragraph"}]}
        result.append((title, body))
    return result


@router.post(
    "/modules/document-import",
    response_model=DocumentImportResponse,
    status_code=status.HTTP_201_CREATED,
)
async def import_document(
    file: Annotated[UploadFile, File()],
    language: Annotated[ModuleLanguage, Form()],
    db: AsyncSession = Depends(get_db),
    author: User = Depends(require_content_manager),
    s3_client: S3Client = Depends(get_s3_client),
) -> DocumentImportResponse:
    """Convert an uploaded document into a fresh, unpublished draft module.

    `language` is supplied by the author rather than guessed: it decides the
    text-search configuration the resulting pages are indexed under, exactly
    as it does for a module created by hand.
    """
    settings = get_settings()
    data = await read_upload_within_cap(file, settings.import_max_archive_bytes)
    filename = file.filename or "import"

    try:
        fmt = sniff_document_format(filename, data)
        converted: ConvertedDocument = convert_document(
            fmt,
            data,
            filename=filename,
            docx_max_entries=settings.import_max_entries,
            docx_max_compression_ratio=settings.import_max_compression_ratio,
            docx_max_uncompressed_bytes=settings.import_max_uncompressed_bytes,
        )
    except DocumentImportRejected as rejection:
        raise _document_import_error(rejection) from rejection

    issues: list[ConversionIssue] = list(converted.issues)

    # Every extracted image is re-sniffed and re-capped here, even though a
    # DOCX embedded image was already sniffed once during conversion to
    # decide whether to place it at all — the same "trust nothing that arrived
    # inside our own processing" posture `app.routes.transfer.import_module`
    # applies to a native import's assets.
    sniffed_images: list[tuple[ConvertedImage, str, str]] = []
    total_image_bytes = 0
    for image in converted.images:
        if len(image.data) > settings.asset_max_image_bytes:
            issues.append(
                ConversionIssue(
                    "image_dropped",
                    f"An embedded image ({image.filename}) was larger than the "
                    f"{settings.asset_max_image_bytes // (1024 * 1024)} MB limit and was "
                    "dropped.",
                )
            )
            continue
        try:
            sniffed = sniff_upload(image.data, kind="image", filename=image.filename)
        except UploadRejected as rejection:
            issues.append(
                ConversionIssue(
                    "image_dropped",
                    f"An embedded image ({image.filename}) could not be imported: "
                    f"{rejection.message}",
                )
            )
            continue
        total_image_bytes += len(image.data)
        if total_image_bytes > settings.asset_max_module_bytes:
            issues.append(
                ConversionIssue(
                    "image_dropped",
                    f"An embedded image ({image.filename}) was dropped: this module's "
                    f"images would exceed the {settings.asset_max_module_bytes // (1024 * 1024)} "
                    "MB storage limit.",
                )
            )
            continue
        sniffed_images.append((image, sniffed.content_type, sniffed.filename))

    group = ModuleTranslationGroup()
    db.add(group)
    await db.flush()

    module = Module(
        translation_group_id=group.id,
        language=language,
        title=converted.title,
        created_by=author.id,
        last_edited_by=author.id,
    )
    db.add(module)
    await db.flush()
    group.primary_module_id = module.id

    urls_by_placeholder: dict[str, str | None] = {
        image.placeholder: None for image in converted.images
    }
    written_keys: list[str] = []
    try:
        for image, content_type, image_filename in sniffed_images:
            new_id = uuid.uuid4()
            key = object_key(module.id, new_id)
            db.add(
                ModuleAsset(
                    id=new_id,
                    module_id=module.id,
                    kind="image",
                    object_key=key,
                    content_type=content_type,
                    size_bytes=len(image.data),
                    original_filename=image_filename,
                    uploaded_by=author.id,
                )
            )
            await db.flush()
            await put_asset(
                s3_client, key=key, data=image.data, content_type=content_type, download_filename=None
            )
            written_keys.append(key)
            urls_by_placeholder[image.placeholder] = asset_url(module.id, new_id)
    except Exception:
        # Best effort, same posture as `app.routes.transfer.import_module`:
        # the transaction rolls back the rows, but not objects already
        # written to the store, so those have to be unwound by hand.
        for key in written_keys:
            try:
                await delete_asset(s3_client, key=key)
            except Exception:
                logger.exception("Could not remove an imported document's asset object: %s", key)
        raise

    rewritten_pages = [
        (page.title, _rewrite_image_placeholders(page.body, urls_by_placeholder))
        for page in converted.pages
    ]
    rewritten_pages = _drop_empty_pages(rewritten_pages, issues)

    for position, (title, body) in enumerate(rewritten_pages):
        validated_body, search_text = validate_page_body(body, SCHEMA_VERSION)
        db.add(
            ModulePage(
                module_id=module.id,
                position=position,
                title=title,
                body=validated_body,
                schema_version=SCHEMA_VERSION,
                search_config=TEXT_SEARCH_CONFIGS[language],
                search_text=search_text,
            )
        )

    await record_audit_log(
        db,
        actor_user_id=author.id,
        action="module_document_imported",
        detail={
            "module_id": str(module.id),
            "title": module.title,
            "source_format": fmt,
            "original_filename": filename,
            "page_count": len(rewritten_pages),
            "asset_count": len(sniffed_images),
            "issue_count": len(issues),
        },
    )
    await db.commit()
    await db.refresh(module)

    return DocumentImportResponse(
        module=await module_response(db, module),
        conversion_report=[
            ConversionReportEntry(code=issue.code, message=issue.message) for issue in issues
        ],
    )
