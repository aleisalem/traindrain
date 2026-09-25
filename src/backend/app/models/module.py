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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.tag import Tag, module_tags

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
    # The snapshot learners read. Never the draft: editing a published module
    # edits `module_pages`, and nobody sees that work until the next publish
    # repoints this. Left pointing at the last version on unpublish, so the
    # history stays resolvable and republishing is a status change.
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "module_versions.id",
            use_alter=True,
            name="fk_modules_current_version",
            ondelete="SET NULL",
        ),
    )
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
    # The version number `current_version_id` pointed at just before a delete
    # cleared it and purged the row it named. Written once, at delete time
    # (ticket 11): the tombstone's own memory of what it was on, independent
    # of any one learner's `completed_version_number`.
    deleted_version_number: Mapped[int | None] = mapped_column(Integer)
    # Free-text labels a Content Manager attaches for search and filtering
    # (ticket 10). Live metadata, not part of a version snapshot — a tag added
    # after publishing is findable immediately, without a republish.
    tags: Mapped[list[Tag]] = relationship(secondary=module_tags, lazy="selectin")


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


class ModuleVersion(Base):
    """An immutable snapshot of one module at the moment it was published.

    Learners never read `module_pages` — those are the working draft. They read
    the snapshot the module's `current_version_id` points at, which is why an
    author can revise a live module without anyone seeing a half-finished edit.

    Immutable is meant literally: a `BEFORE UPDATE` trigger in the database
    refuses any update to a row here. A version is the evidence of what a
    learner was made to read, and evidence that can be edited afterwards is not
    evidence. Only ticket 11's module delete removes one, by cascade.
    """

    __tablename__ = "module_versions"
    __table_args__ = (
        UniqueConstraint("module_id", "version_number", name="uq_module_versions_number"),
        Index("ix_module_versions_module_number", "module_id", "version_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    module_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("modules.id", ondelete="CASCADE"), nullable=False
    )
    # 1, 2, 3… per module, so "Anna completed v2" is a thing a person can say.
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    published_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    # minor | substantive — the author's answer to "does everyone have to read
    # this again?". Acted on at publish time: `substantive` supersedes every
    # completion of this translation group and resets its learners' page-view
    # progress (`_send_learners_back` in `app.routes.content`).
    revision_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    # Title, description, language, estimated duration, and the full page
    # array — including each page's id — as they stood at publish time.
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


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


class ModuleProgress(Base):
    """How far one learner has got through one body of material.

    Keyed on the *translation group*, not the module: a learner has one record
    per body of material however many language variants of it exist, so reading
    the German variant and then switching to the English one is one journey
    rather than two (ticket 6). `module_id` records the variant actually read,
    so a report can say which text somebody was shown.

    Deliberately **not** keyed on an assignment. Progress is something a person
    did, and it has to survive an assignment being removed or the learner
    leaving the group it was targeted at — the assignment is looked up at read
    time (ticket 7) rather than baked into this row.
    """

    __tablename__ = "module_progress"
    __table_args__ = (
        UniqueConstraint("user_id", "translation_group_id", name="uq_module_progress_learner"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    translation_group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("module_translation_groups.id", ondelete="CASCADE"),
        nullable=False,
    )
    # The variant actually read. Plain foreign key: a deleted module leaves a
    # tombstone row behind (ticket 11), so this keeps resolving.
    module_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("modules.id"), nullable=False
    )
    # The ids of the pages this learner has seen, as they appear in the version
    # snapshot they were reading. Emptied by a substantive republish: a page
    # keeps its id across an edit, so views collected against the old text would
    # otherwise satisfy the new one's "read every page" check unread.
    pages_viewed: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    # Where to put them back when they return. Deliberately *no* foreign key to
    # `module_pages`: these ids come from an immutable snapshot, and the draft
    # row one of them names may since have been deleted by an author. A
    # constraint here would make a learner's bookmark something an author could
    # break, or block a delete the author is entitled to make.
    current_page_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Which version they attested to, so "who has read the current text" stays
    # answerable after the module is revised.
    completed_version_number: Mapped[int | None] = mapped_column(Integer)
    # Which variant that version number belongs to. `module_id` above moves on
    # an explicit language switch (ticket 6) and no longer necessarily names
    # the variant that was completed — its own version numbering means
    # something else — so this is set only by completion, and a switch leaves
    # it alone.
    completed_module_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("modules.id")
    )
    # Set by a substantive republish to mark a completion as no longer current.
    # Never erases `completed_at` — the person did read v2, and that stays true.
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
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
