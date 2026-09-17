"""Did people do the training? Two response shapes for `GET
/api/content/modules/{id}/report`, chosen server-side by the caller's role —
see `app.routes.reports`. Never a query parameter: the shape a Content Manager
is entitled to is not a client-side choice.
"""

import uuid
from datetime import date, datetime

from pydantic import BaseModel

from app.reporting import LearnerState


class ModuleReportGroupSummary(BaseModel):
    """One targeted group's material, aggregated — no names, only counts.

    `overdue` is not a fifth, mutually-exclusive bucket: it counts learners
    who are also `not_started` or `in_progress` but past their due date, the
    same way `app.assignments.is_overdue` reads for one learner's own list.
    """

    group_id: uuid.UUID
    group_name: str
    member_count: int
    completed: int
    in_progress: int
    not_started: int
    overdue: int


class ContentManagerModuleReport(BaseModel):
    translation_group_id: uuid.UUID
    groups: list[ModuleReportGroupSummary]


class ModuleReportLearner(BaseModel):
    """One targeted learner, exactly as far as an Administrator may see one.

    `completed_at` and `completed_version_number` are kept even when `state`
    is `in_progress` because a substantive republish superseded them — the
    prior completion is a fact about the past that stays visible, per
    `app.reporting.LearnerStanding`.
    """

    user_id: uuid.UUID
    name: str
    email: str
    state: LearnerState
    overdue: bool
    due_date: date | None
    completed_at: datetime | None
    completed_version_number: int | None


class AdministratorModuleReport(BaseModel):
    translation_group_id: uuid.UUID
    learners: list[ModuleReportLearner]
