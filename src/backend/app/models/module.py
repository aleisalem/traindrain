import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

# The generated `search_tsv` expression. A stored generated column has to be
# IMMUTABLE, and `text::regconfig` is not — so the configuration is spelled out
# as a CASE over literal regconfigs rather than cast from the stored string.
# The value of `search_config` itself comes from the module's stored language
# at write time, never from the query.
SEARCH_TSV_EXPRESSION = (
    "to_tsvector("
    "case when search_config = 'german' then 'german'::regconfig "
    "else 'english'::regconfig end, "
    "coalesce(search_text, '')"
    ")"
)


class ModuleTranslationGroup(Base):
    """The body of material a set of language variants share.

    Every module belongs to exactly one group, and a standalone module gets a
    group of its own on creation. Assignments (Release 1, ticket 7) target a
    group rather than a module, so adding a translation later never requires
    rewriting an existing assignment.
    """

    __tablename__ = "module_translation_groups"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Nullable and use_alter: the group row is written before the module that
    # will be its primary exists, and the two tables reference each other, so
    # this constraint has to be added after both tables are created.
    primary_module_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("modules.id", use_alter=True, name="fk_translation_group_primary_module"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Module(Base):
    """One language variant of a piece of learning material."""

    __tablename__ = "modules"
    __table_args__ = (UniqueConstraint("translation_group_id", "language"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    translation_group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("module_translation_groups.id"), nullable=False, index=True
    )
    # Immutable after creation — the full-text search configuration for a
    # module's pages is derived from this value at write time (ticket 2), so a
    # language change would silently leave the stored index stemmed for the
    # wrong language. A different language is a new variant, not an edit.
    language: Mapped[str] = mapped_column(String(5), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    estimated_duration_minutes: Mapped[int | None] = mapped_column(Integer)
    catalog_visible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # draft | published | deleted — `deleted` is terminal.
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    # Optimistic-lock token for draft mutations, so two Content Managers
    # editing the same draft get a conflict rather than a lost edit.
    draft_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # There is no module ownership — any Content Manager may edit any module —
    # but these record who did what, alongside the audit log.
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    last_edited_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ModulePage(Base):
    """One page of a module's working draft.

    The body is a validated ProseMirror document tree, never HTML — see
    `app.content.validation` for why, and for what "validated" means here.
    """

    __tablename__ = "module_pages"
    __table_args__ = (
        # DEFERRABLE so a reorder can renumber every page inside one
        # transaction without contorting the update order to dodge a
        # transient collision.
        UniqueConstraint(
            "module_id", "position", deferrable=True, initially="DEFERRED"
        ),
        Index("ix_module_pages_search_tsv", "search_tsv", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    module_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("modules.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    # Which version of the checked-in schema this document was validated
    # against, so a future schema change knows what it is looking at.
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    # 'english' | 'german' — resolved from the module's language on write.
    search_config: Mapped[str] = mapped_column(String(20), nullable=False)
    # Populated by walking the tree and concatenating its text nodes.
    search_text: Mapped[str | None] = mapped_column(Text)
    search_tsv: Mapped[str | None] = mapped_column(
        TSVECTOR, Computed(SEARCH_TSV_EXPRESSION, persisted=True)
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ModuleAsset(Base):
    """An image or a downloadable file belonging to a module.

    The bytes live in a private object store, never in the database and never
    served directly — `GET /api/modules/{id}/assets/{asset_id}` authorizes the
    caller and then redirects to a short-lived presigned URL.

    `content_type` is what the *bytes* turned out to be (see
    `app.content.uploads`), not what the client declared, and it is what the
    object is stored and later served under.
    """

    __tablename__ = "module_assets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # No `index=True`: the composite `(module_id, created_at)` index the
    # migration creates already serves a lookup by module on its leading
    # column, and declaring a second one here would leave the model and the
    # migration disagreeing — which `alembic revision --autogenerate` would
    # then keep trying to reconcile.
    module_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("modules.id", ondelete="CASCADE"),
        nullable=False,
    )
    # image | attachment — constrained in the database by `ck_module_assets_kind`.
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    # `modules/{module_id}/assets/{asset_id}` — derived from opaque UUIDs, so
    # nothing about a module's content makes another module's key guessable.
    object_key: Mapped[str] = mapped_column(String(300), nullable=False, unique=True)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # Kept for the download name only. Sanitized to a bare basename before it
    # is stored, because it is echoed into a `Content-Disposition` header.
    original_filename: Mapped[str] = mapped_column(String(200), nullable=False)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ModuleEditSession(Base):
    """Who currently has a module open in the authoring screen.

    Presence, not a lock. Concurrent editing of a module's metadata is
    deliberately *allowed* — this row is what lets the UI say who else is in
    here, so the author decides knowingly rather than discovering the
    overwrite afterwards.

    Kept fresh by a heartbeat from the open editor; a row whose `last_seen_at`
    has aged past the presence window counts as gone, whether the author
    closed the tab, lost their network, or their laptop went to sleep.
    """

    __tablename__ = "module_edit_sessions"

    module_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("modules.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
