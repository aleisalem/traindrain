"""Who has to read a body of material, and by when.

Deliberately separate from `app.schemas.modules`: an assignment names a target
(a group, or — Administrator only — an individual), and the response shape has
to keep a Content Manager away from a colleague's identity even while showing
them the assignment exists.
"""

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.schemas.modules import ModuleActor

TargetType = Literal["user", "group"]
Requirement = Literal["mandatory", "recommended"]


class AssignmentCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_type: TargetType
    target_id: uuid.UUID
    due_date: date | None = None
    requirement: Requirement
    # Defaults on, unlike `revision_kind`: whether to chase a deadline is a
    # meaningful choice, but not one that needs to force an explicit answer
    # the way "does everyone have to read this again" does.
    auto_reminders: bool = True


class AssignmentTarget(BaseModel):
    """Who an assignment names, resolved just enough to display it.

    A group target always carries its name — a Content Manager already sees
    that much through `GET /api/content/groups`. A user target's name is
    included only for an Administrator (`name` is `None` otherwise): showing
    it to a Content Manager would hand them a colleague's identity through an
    endpoint that exists precisely to avoid that.
    """

    model_config = ConfigDict(extra="forbid")

    type: TargetType
    id: uuid.UUID
    name: str | None


class AssignmentResponse(BaseModel):
    id: uuid.UUID
    translation_group_id: uuid.UUID
    target: AssignmentTarget
    due_date: date | None
    requirement: Requirement
    auto_reminders: bool
    assigned_by: ModuleActor
    created_at: datetime


class ContentGroupResponse(BaseModel):
    """A group, as far as a Content Manager may see one: a name, a description,
    and how many people are in it — never who they are.
    """

    id: uuid.UUID
    name: str
    description: str | None
    member_count: int
