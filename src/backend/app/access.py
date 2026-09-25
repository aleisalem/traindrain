"""Who may read a module's material.

One decision, in one place, because it is asked from three directions — the
learner opening a module, the learner fetching one of its attachments, and the
author previewing their own draft — and three copies of it would eventually
disagree. `authorize_asset_access` in `app.routes.assets` and the learner routes
in `app.routes.learning` both come here and nowhere else.

Implicit deny throughout: an authenticated user gets nothing until a rule admits
them.

Both functions here are pure predicates over data the caller already holds.
That is why `may_read_module`'s assignment rule — "the module is assigned to
you, directly or through a group you belong to" — arrives as a precomputed
`assigned_group_ids` rather than a lookup this function makes itself: it is a
fact about the *user*, one query per request (`app.assignments`), and taking
it as a parameter here is what keeps it that way rather than one query per
module a naive call site would fall into.
"""

import uuid
from collections.abc import Collection

from fastapi import HTTPException, status

from app.models import Module, User

AUTHORING_ROLES = frozenset({"Content Manager", "Administrator"})


def is_author(user: User) -> bool:
    """May this user see draft material — anyone's, including unpublished?"""
    return bool(AUTHORING_ROLES & {role.name for role in user.roles})


def is_administrator(user: User) -> bool:
    """Does this user hold the Administrator role?

    The one answer to a question several call sites otherwise re-derive from
    `user.roles` themselves — `require_administrator` in `app.dependencies`
    and the individual-assignment gate in `app.routes.assignments` both ask
    this rather than re-spelling the role check.
    """
    return "Administrator" in {role.name for role in user.roles}


def may_read_module(
    user: User,
    module: Module,
    *,
    assigned_group_ids: Collection[uuid.UUID] = frozenset(),
) -> bool:
    """May this user read this module?

    Authors may read any module, published or not: that is the access they
    already have to its pages through the authoring API, and previewing is the
    point of it.

    Everyone else is a learner, and a learner may read a module only once it is
    published, and only while it is either in the open catalog or assigned to
    them — directly, or through a group they currently belong to
    (`assigned_group_ids`, built by the caller from `app.assignments`). A
    module that is neither is genuinely unreachable rather than merely absent
    from a list — including for a learner who has the URL.
    """
    if is_author(user):
        return True
    if module.status != "published":
        return False
    return module.catalog_visible or module.translation_group_id in assigned_group_ids


def ensure_module_editable(module: Module) -> None:
    """Refuse any further authoring action on a deleted module.

    `deleted` is terminal (ticket 11): a delete purges `module_pages`,
    `module_versions`, and `module_assets`, so there is nothing left to edit,
    publish, duplicate, or assign — every mutating authoring route calls this
    before doing its own work, alongside `get_module_or_404`.
    """
    if module.status == "deleted":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "module_deleted",
                "message": "This module has been deleted and can no longer be changed.",
            },
        )
