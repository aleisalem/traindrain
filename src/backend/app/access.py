"""Who may read a module's material.

One decision, in one place, because it is asked from three directions — the
learner opening a module, the learner fetching one of its attachments, and the
author previewing their own draft — and three copies of it would eventually
disagree. `authorize_asset_access` in `app.routes.assets` and the learner routes
in `app.routes.learning` both come here and nowhere else.

Implicit deny throughout: an authenticated user gets nothing until a rule admits
them.

Both functions here are pure predicates over data the caller already holds.
That matters for what comes next: ticket 7's rule — "the module is assigned to
you, directly or through a group you belong to" — is a fact about the *user*,
one query per request, not a lookup per module. It belongs in a small audience
value built once at the top of a request and asked per module:

    ModuleAudience(is_author=..., assigned_groups=frozenset(...)).may_read(module)

Putting that query inside this predicate instead would make one query per row
the natural way to call it, which is exactly the shape to avoid.
"""

from app.models import Module, User

AUTHORING_ROLES = frozenset({"Content Manager", "Administrator"})


def is_author(user: User) -> bool:
    """May this user see draft material — anyone's, including unpublished?"""
    return bool(AUTHORING_ROLES & {role.name for role in user.roles})


def may_read_module(user: User, module: Module) -> bool:
    """May this user read this module?

    Authors may read any module, published or not: that is the access they
    already have to its pages through the authoring API, and previewing is the
    point of it.

    Everyone else is a learner, and a learner may read a module only while the
    author has both published it and opted it into the open catalog. A module
    that was never opened to everyone is genuinely unreachable rather than
    merely absent from a list — including for a learner who has the URL.

    Ticket 7 adds the second learner branch — the module is assigned to them —
    as an extra term here, with the assigned groups precomputed by its caller
    rather than looked up per module (see the module docstring).
    """
    if is_author(user):
        return True
    return module.status == "published" and module.catalog_visible
