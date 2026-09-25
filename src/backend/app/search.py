"""Module search and tag filtering, shared by the authoring list and the catalog.

One decision, in one place, in the spirit of `app.access` and `app.assignments`:
the authoring module list (`GET /api/content/modules`) and the learner catalog
(`GET /api/catalog/modules`) ask for the same two things — text matched against
a module's title and description, and a set of tags a module must carry — and
duplicating the query construction in both routes would leave two places that
could disagree about what "matches" means.
"""

import uuid

from sqlalchemy import ColumnElement, Select, case, cast, func, select
from sqlalchemy.dialects.postgresql import REGCONFIG
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Module, Tag, module_tags

# The text-search configuration is derived from each module's own stored
# `language` — never guessed from the query string — so a German module is
# matched with German stemming and an English one with English, whichever
# language the request happens to be typed in. Mirrors the same case-over-
# literals pattern `ModulePage.search_tsv` uses, for the same reason: a stored
# generated column has to be IMMUTABLE, and this expression is written so it
# could be one if it ever needed to be.
_SEARCH_CONFIG = cast(case((Module.language == "de", "german"), else_="english"), REGCONFIG)


def module_search_predicate(query: str) -> ColumnElement[bool]:
    """A WHERE clause matching a module's title and description against `query`."""
    vector = func.to_tsvector(
        _SEARCH_CONFIG, func.concat_ws(" ", Module.title, func.coalesce(Module.description, ""))
    )
    return vector.op("@@")(func.plainto_tsquery(_SEARCH_CONFIG, query))


def normalize_tag_filter(tags: list[str] | None) -> list[str]:
    """Lowercase, strip, and dedupe tag names for a filter query.

    Lenient by design — filtering is a GET, and a blank or oddly-cased value
    here should simply match nothing rather than fail the request the way the
    stricter write-side validator (`app.schemas.modules`) does.
    """
    if not tags:
        return []
    seen: list[str] = []
    for raw in tags:
        name = raw.strip().lower()
        if name and name not in seen:
            seen.append(name)
    return seen


def apply_tag_filter(statement: Select[tuple[Module]], tag_names: list[str]) -> Select[tuple[Module]]:
    """Narrow `statement` to modules carrying every one of `tag_names`.

    One `Module.id.in_(...)` per requested tag rather than a single join, so
    two tags combine as AND — a module has to carry both, not either — without
    the row-multiplying join a single query would need to express the same
    thing.
    """
    for name in tag_names:
        statement = statement.where(
            Module.id.in_(
                select(module_tags.c.module_id)
                .select_from(module_tags.join(Tag, Tag.id == module_tags.c.tag_id))
                .where(Tag.name == name)
            )
        )
    return statement


async def get_or_create_tags(db: AsyncSession, names: list[str]) -> list[Tag]:
    """Every tag row for these (already-normalized) names, creating any that are new.

    Each insert goes through `ON CONFLICT DO NOTHING` rather than a plain
    insert-then-catch, so two authors typing the same brand-new tag at the same
    moment produce one row and neither request fails.
    """
    if not names:
        return []
    for name in names:
        await db.execute(
            pg_insert(Tag).values(id=uuid.uuid4(), name=name).on_conflict_do_nothing(
                index_elements=["name"]
            )
        )
    rows = (await db.execute(select(Tag).where(Tag.name.in_(names)))).scalars()
    by_name = {tag.name: tag for tag in rows}
    return [by_name[name] for name in names]
