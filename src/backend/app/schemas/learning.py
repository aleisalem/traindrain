"""What a learner is sent: the catalog, one module to read, and their progress.

Deliberately a separate module from `app.schemas.modules`, because these are a
different audience's view of the same material. Nothing here carries a draft, a
`draft_revision`, or an author's name — a learner reads a frozen version
snapshot, and who wrote it is not part of the material.
"""

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.schemas.assignments import Requirement
from app.schemas.modules import ModuleLanguage


class CatalogEntry(BaseModel):
    """One body of material in the open catalog.

    Addressed by `translation_group_id` rather than module id: which language
    variant a learner reads is resolved when they open it, so the catalog links
    to the material and not to one particular text of it.
    """

    translation_group_id: uuid.UUID
    language: str
    title: str
    description: str | None
    estimated_duration_minutes: int | None
    page_count: int
    # The learner's own state, so the catalog can say "continue" rather than
    # "start" without a second round trip.
    started: bool
    completed_at: datetime | None
    # Sent alongside `completed_at` rather than folded into it: a card that
    # showed "completed" for material the learner has been asked to read again
    # would be contradicting the module it links to.
    superseded_at: datetime | None


class LearnerPage(BaseModel):
    """One page of a published version, as a learner reads it.

    `body` is the validated ProseMirror tree from the snapshot — never HTML,
    and rendered on the client through the static renderer.
    """

    id: uuid.UUID
    position: int
    title: str
    schema_version: int
    body: dict[str, Any]


class LearnerAttachment(BaseModel):
    """A file a learner may download while reading.

    `url` is the authorizing API path, exactly as it is for authors: the
    redirect it returns is what mints a short-lived signed URL, and the caller
    is checked again on every fetch.
    """

    id: uuid.UUID
    url: str
    original_filename: str
    content_type: str
    size_bytes: int


class ProgressState(BaseModel):
    """How far through this material the caller is.

    `pages_viewed` is sent back in full rather than as a count, because the
    viewer has to know *which* pages are still outstanding to say so, and to
    decide whether the attestation control is live.
    """

    pages_viewed: list[uuid.UUID]
    current_page_id: uuid.UUID | None
    started_at: datetime
    completed_at: datetime | None
    completed_version_number: int | None
    # The variant `completed_version_number` belongs to — not necessarily the
    # module a learner is reading now, since an explicit language switch moves
    # that on to a different variant with its own, unrelated version numbers.
    completed_module_id: uuid.UUID | None
    # Set when a substantive republish puts a completed learner back in the
    # outstanding pile. The completion itself is never erased.
    superseded_at: datetime | None


class LearnerModule(BaseModel):
    """Everything the viewer needs to render one module, in one response."""

    translation_group_id: uuid.UUID
    module_id: uuid.UUID
    language: str
    title: str
    description: str | None
    estimated_duration_minutes: int | None
    version_number: int
    pages: list[LearnerPage]
    attachments: list[LearnerAttachment]
    # `None` until the learner has actually read a page. Opening a module is a
    # read and stays one — it writes nothing — so nothing is recorded about
    # somebody who clicked the wrong card and left again.
    progress: ProgressState | None
    # Every language of this material the learner may read, so the viewer can
    # offer a switch only when there is genuinely a choice to make.
    available_languages: list[str]


class SwitchLanguageRequest(BaseModel):
    """An explicit request to read a different language of this material."""

    model_config = ConfigDict(extra="forbid")

    language: ModuleLanguage


class LearnerModuleSummary(BaseModel):
    """One line of "my learning": something assigned, started, finished, or
    any combination of those.

    `started_at` is `None` for a row that exists only because the material is
    assigned and nobody has opened it yet — the union this list represents is
    "what I have touched" plus "what I have been told to touch".
    """

    translation_group_id: uuid.UUID
    title: str
    language: str
    estimated_duration_minutes: int | None
    started_at: datetime | None
    completed_at: datetime | None
    completed_version_number: int | None
    superseded_at: datetime | None
    # Whether it can still be opened. A module unpublished since the learner
    # read it stays on this list — the completion is theirs — but reopening it
    # is not on offer.
    available: bool
    # From the assignment with the nearest due date covering this material, if
    # any — a module only ever opened via the catalog carries neither.
    due_date: date | None
    requirement: Requirement | None
    overdue: bool
