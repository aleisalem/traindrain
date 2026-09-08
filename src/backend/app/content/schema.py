"""The one ProseMirror schema, loaded from the JSON checked into this package.

`prosemirror_schema.json` is the single source of truth for what a page body
may contain. The backend validator reads it here; the Tiptap editor reads a
mirrored copy under `src/frontend/src/content/`, and a frontend test fails if
the two ever drift apart.

Changing the schema is a migration, not an edit: Tiptap silently drops content
outside its schema, so widening or narrowing the node set needs its own ticket
that decides what happens to documents already stored under the old version.
That is what `schema_version` on every stored document is for.
"""

import json
from functools import cache
from pathlib import Path
from typing import Any

from prosemirror.model import Schema

_SCHEMA_PATH = Path(__file__).with_name("prosemirror_schema.json")


@cache
def _schema_document() -> dict[str, Any]:
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


SCHEMA_VERSION: int = _schema_document()["schemaVersion"]
CONSTRAINTS: dict[str, Any] = _schema_document()["constraints"]

# Which PostgreSQL text-search configuration a module's pages are indexed
# under. Chosen from the module's stored `language` at write time and saved on
# the page row — never inferred from the query text, which would stem a German
# search with English rules.
TEXT_SEARCH_CONFIGS = {"en": "english", "de": "german"}


@cache
def prosemirror_schema() -> Schema:
    return Schema(_schema_document()["spec"])


@cache
def allowed_node_attrs() -> dict[str, frozenset[str]]:
    """Per-node attribute allowlist, derived from the schema itself.

    prosemirror-py drops an attribute it doesn't know about and accepts the
    document, which is exactly the "sanitize and accept" behaviour this
    platform refuses. The validator checks incoming attributes against this
    map first, so an unknown one is a rejection.
    """
    nodes = _schema_document()["spec"]["nodes"]
    return {name: frozenset(spec.get("attrs", {})) for name, spec in nodes.items()}


@cache
def allowed_mark_attrs() -> dict[str, frozenset[str]]:
    marks = _schema_document()["spec"]["marks"]
    return {name: frozenset(spec.get("attrs", {})) for name, spec in marks.items()}
