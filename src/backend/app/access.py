"""Who may read a module's material.

One decision, in one place, because it is asked from three directions — the
learner opening a module, the learner fetching one of its attachments, and the
author previewing their own draft — and three copies of it would eventually
disagree. `authorize_asset_access` in `app.routes.assets` and the learner routes
in `app.routes.learning` both come here and nowhere else.

Implicit deny throughout: an authenticated user gets nothing until a rule admits
them. Ticket 7's assignment branch goes in `may_read_module` alongside the
catalog branch, which is why it already takes an `AsyncSession`.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Module, User

AUTHORING_ROLES = frozenset({"Content Manager", "Administrator"})


def is_author(user: User) -> bool:
    """May this user see draft material — anyone's, including unpublished?"""
    return bool(AUTHORING_ROLES & {role.name for role in user.roles})


async def may_read_module(db: AsyncSession, user: User, module: Module) -> bool:
    """May this user read this module?

    Authors may read any module, published or not: that is the access they
    already have to its pages through the authoring API, and previewing is the
    point of it.

    Everyone else is a learner, and a learner may read a module only while the
    author has both published it and opted it into the open catalog. A module
    that was never opened to everyone is genuinely unreachable rather than
    merely absent from a list — including for a learner who has the URL.

    Ticket 7 adds the second learner branch here: the module is assigned to
    them, directly or through a group they currently belong to.
    """
    if is_author(user):
        return True
    return module.status == "published" and module.catalog_visible
