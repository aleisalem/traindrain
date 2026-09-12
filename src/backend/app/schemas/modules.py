import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# The languages the platform ships content in. Kept as a Literal rather than a
# free string so an unsupported language is a 422 at the edge, before it can
# reach the module row whose stored language later picks a text-search
# configuration.
ModuleLanguage = Literal["en", "de"]

# An illustration on a page, or a file a learner downloads. Kept as a Literal so
# an unknown kind is a 422 at the edge, before it reaches the row whose CHECK
# constraint would otherwise be the only thing refusing it.
AssetKind = Literal["image", "attachment"]

# Does everyone have to read this again? A Literal with no default, so the
# question cannot be answered by omission — publishing without deciding is a
# 422, not a quiet `minor`.
RevisionKind = Literal["minor", "substantive"]


class ModuleCreateRequest(BaseModel):
    # extra="forbid" is what makes an attempt to smuggle `created_by`,
    # `status`, or `draft_revision` into the payload a 422 rather than a
    # silently-ignored field — those are set server-side, never by the client.
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    language: ModuleLanguage
    description: str | None = None
    estimated_duration_minutes: int | None = Field(default=None, ge=1, le=10_000)

    @field_validator("title")
    @classmethod
    def _title_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("A module needs a title.")
        return value

    @field_validator("description")
    @classmethod
    def _blank_description_is_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class ModuleUpdateRequest(BaseModel):
    """A partial update — a field left out is left alone.

    `language` is absent deliberately: it is fixed at creation, because the
    full-text search configuration for a module's pages is derived from it at
    write time. A different language is a new variant (ticket 6), not an edit.
    """

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    estimated_duration_minutes: int | None = Field(default=None, ge=1, le=10_000)
    # Whether learners may find this module in the open catalog and read it of
    # their own accord. Defaults to false on the row, so a module reaches
    # nobody until an author says here that it should.
    catalog_visible: bool | None = None

    @field_validator("title")
    @classmethod
    def _title_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("A module needs a title.")
        return value

    @field_validator("description")
    @classmethod
    def _blank_description_is_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @field_validator("catalog_visible")
    @classmethod
    def _catalog_visible_not_null(cls, value: bool | None) -> bool | None:
        # `None` here means "left out", and a field left out is left alone. An
        # explicit null is a different thing and would write NULL into a
        # NOT NULL column, so it is refused at the edge rather than at the row.
        # This only fires on a value the client actually sent — pydantic does
        # not validate the default.
        if value is None:
            raise ValueError("catalog_visible must be true or false.")
        return value


class ModuleActor(BaseModel):
    """Who created or last edited a module, or uploaded one of its assets.

    Carries a display name rather than the full user record: authoring must
    not become a route into the staff directory.
    """

    id: uuid.UUID
    display_name: str

    @classmethod
    def from_user(cls, user: Any) -> "ModuleActor":
        """Build one from a `User`.

        Lives here rather than in each route so there is one answer to "what do
        we call this person" — a name if they have one, their email if not.
        Typed loosely to keep the schema layer from importing the models.
        """
        name = " ".join(part for part in (user.first_name, user.last_name) if part).strip()
        return cls(id=user.id, display_name=name or user.email)


class ModuleEditorsResponse(BaseModel):
    """Who else currently has this module open.

    Never includes the caller — the question the authoring screen is asking is
    "who am I sharing this with", and listing yourself back answers a
    different one.
    """

    editors: list[ModuleActor]


class PageCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The module's optimistic-lock token, so two Content Managers editing the
    # same draft get a 409 rather than one silently overwriting the other.
    draft_revision: int
    title: str = Field(min_length=1, max_length=200)
    schema_version: int
    # Validated against the checked-in ProseMirror schema in the route, not
    # here: pydantic can say "this is an object", but only
    # `app.content.validation` can say the document conforms.
    body: dict[str, Any]

    @field_validator("title")
    @classmethod
    def _title_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("A page needs a title.")
        return value


class PageUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_revision: int
    title: str | None = Field(default=None, min_length=1, max_length=200)
    schema_version: int | None = None
    body: dict[str, Any] | None = None

    @field_validator("title")
    @classmethod
    def _title_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("A page needs a title.")
        return value


class PageDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_revision: int


class PageReorderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_revision: int
    # Every one of the module's page ids, exactly once, in the order wanted.
    page_ids: list[uuid.UUID] = Field(min_length=1)


class PageResponse(BaseModel):
    id: uuid.UUID
    position: int
    title: str
    schema_version: int
    body: dict[str, Any]
    updated_at: datetime


class PagesResponse(BaseModel):
    """A module's draft pages, with the token the next write has to carry."""

    draft_revision: int
    schema_version: int
    pages: list[PageResponse]


class AssetResponse(BaseModel):
    """One image or attachment on a module.

    `url` is the API path that authorizes and redirects — never a presigned
    URL. A signed URL in a JSON response would outlive the check that produced
    it and could be forwarded to someone the check would have refused.
    """

    id: uuid.UUID
    kind: AssetKind
    url: str
    content_type: str
    size_bytes: int
    original_filename: str
    uploaded_by: ModuleActor
    created_at: datetime
    # How many of this module's draft pages reference this asset. Shown so an
    # author deleting an image knows they are about to leave a gap on a page,
    # rather than discovering it in the preview afterwards.
    referenced_by_pages: int
    # How many *published versions* reference it. A far heavier warning: a
    # version snapshot is immutable, so an asset deleted out from under one
    # leaves a hole in material learners are reading that no edit can repair.
    referenced_by_versions: int


class AssetsResponse(BaseModel):
    """A module's assets, and how much of its storage budget is left."""

    assets: list[AssetResponse]
    total_bytes: int
    max_module_bytes: int
    max_image_bytes: int
    max_attachment_bytes: int


class PublishRequest(BaseModel):
    """The one question a publish cannot dodge.

    `revision_kind` is required and has no default: whether a revision drags
    every completed learner back through the module is the author's call, and a
    default here would be the system quietly making it for them.
    """

    model_config = ConfigDict(extra="forbid")

    revision_kind: RevisionKind


class RevisionImpactResponse(BaseModel):
    """Who a substantive republish would send back through the material.

    Read before publishing, not after: "everyone who completed this will have
    to read it again" is an abstraction until it says how many people that is,
    and an author deciding between `minor` and `substantive` deserves the
    number while the decision is still open.

    Counted over the module's whole translation group, because that is what a
    learner's progress record is keyed on — one person reading one body of
    material, whichever language variant they happened to open.
    """

    # Completions a substantive publish would mark superseded.
    completed_learners: int
    # People part-way through, whose page-view progress it would reset.
    in_progress_learners: int


class DuplicateRequest(BaseModel):
    """An optional new title for the copy.

    The title is supplied by the caller rather than suffixed server-side,
    because "(copy)" is a word — and a platform that ships in English and
    German has no business inventing one in a single language.
    """

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=200)

    @field_validator("title")
    @classmethod
    def _title_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("A module needs a title.")
        return value


class VersionResponse(BaseModel):
    """One entry of a module's publish history.

    Deliberately without the snapshot itself: the history screen wants to know
    what happened and when, and shipping every published page array to render a
    list would be pounds of payload for a line of text.
    """

    id: uuid.UUID
    version_number: int
    revision_kind: RevisionKind
    published_at: datetime
    published_by: ModuleActor
    # The title as it stood at publish time — a module renamed since then still
    # shows history under the names it actually went out with.
    title: str
    page_count: int


class LinkVariantRequest(BaseModel):
    """Bring an existing standalone module in as this group's translation.

    The source module has to be genuinely standalone — the only module in its
    own translation group — because linking it here would otherwise orphan
    whatever else it was already grouped with.
    """

    model_config = ConfigDict(extra="forbid")

    module_id: uuid.UUID


class SetPrimaryVariantRequest(BaseModel):
    """Which variant a learner whose own language has no translation gets."""

    model_config = ConfigDict(extra="forbid")

    primary_module_id: uuid.UUID


class ModuleResponse(BaseModel):
    id: uuid.UUID
    translation_group_id: uuid.UUID
    language: str
    title: str
    description: str | None
    estimated_duration_minutes: int | None
    status: str
    # Whether learners can find it in the open catalog. Published and
    # catalog-visible are two different decisions: a module can be live for
    # assigned learners (ticket 7) without being on offer to everybody.
    catalog_visible: bool
    # The version learners are reading, or were reading when the module was
    # unpublished. `None` until the first publish.
    current_version_number: int | None
    created_by: ModuleActor
    last_edited_by: ModuleActor
    created_at: datetime
    updated_at: datetime


class TranslationGroupResponse(BaseModel):
    """One body of material: every language it is written in, and which is primary."""

    id: uuid.UUID
    primary_module_id: uuid.UUID | None
    variants: list[ModuleResponse]
