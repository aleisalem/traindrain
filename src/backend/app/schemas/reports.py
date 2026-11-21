"""Did people do the training? Two response shapes for `GET
/api/content/modules/{id}/report`, chosen server-side by the caller's role —
see `app.routes.reports`. Never a query parameter: the shape a Content Manager
is entitled to is not a client-side choice.
"""

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

from app.reporting import LearnerState


class QuizGroupStats(BaseModel):
    """Quiz results for a set of learners — counts and averages only.

    `pass_rate_percent` is learners who ever passed over learners who attempted.
    `average_attempts_to_pass` averages, over those who passed, which attempt
    first passed.
    """

    attempted: int
    passed: int
    pass_rate_percent: int | None
    average_score_percent: int | None
    average_attempts_to_pass: float | None


class QuizQuestionStat(BaseModel):
    """How one question of the current published quiz fared — never an answer."""

    question_id: uuid.UUID
    position: int
    prompt_text: str
    answered: int
    correct: int
    percent_correct: int | None


class QuizReport(BaseModel):
    """Module-wide quiz figures. `overall` counts every learner who attempted,
    including those since erased, so it stays correct after an erase."""

    pass_mark_percent: int
    attempts: int
    overall: QuizGroupStats
    questions: list[QuizQuestionStat]


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
    quiz: QuizGroupStats | None = None


class ContentManagerModuleReport(BaseModel):
    translation_group_id: uuid.UUID
    groups: list[ModuleReportGroupSummary]
    quiz: QuizReport | None = None


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
    # Only meaningful when the module has a quiz; a best score and a count,
    # never an answer.
    best_score_percent: int | None = None
    attempt_count: int = 0


class AdministratorModuleReport(BaseModel):
    translation_group_id: uuid.UUID
    learners: list[ModuleReportLearner]
    quiz: QuizReport | None = None


# --- Campaign reports ---------------------------------------------------------

CampaignLearnerStateName = Literal["completed", "in_progress", "not_started", "suspended"]


class CampaignReportGroupSummary(BaseModel):
    """One targeted group across a campaign — counts and an average, no names.

    The four states are mutually exclusive and sum to `member_count`; `overdue`
    is an overlay on in-progress/not-started learners of an active campaign.
    `average_progress` is the mean percentage of mandatory modules complete.
    """

    group_id: uuid.UUID
    group_name: str
    member_count: int
    completed: int
    in_progress: int
    not_started: int
    overdue: int
    suspended: int
    average_progress: int


class CampaignReportModule(BaseModel):
    translation_group_id: uuid.UUID
    title: str | None
    requirement: str
    unavailable: bool


class ContentManagerCampaignReport(BaseModel):
    campaign_id: uuid.UUID
    campaign_name: str
    status: str
    due_date: date | None
    modules: list[CampaignReportModule]
    groups: list[CampaignReportGroupSummary]


class CampaignReportModuleCell(BaseModel):
    translation_group_id: uuid.UUID
    requirement: str
    state: Literal["completed", "in_progress", "not_started"]
    unavailable: bool
    completed_at: datetime | None
    completed_version_number: int | None


class CampaignReportLearner(BaseModel):
    user_id: uuid.UUID
    name: str
    email: str
    state: CampaignLearnerStateName
    overdue: bool
    required_total: int
    required_done: int
    progress_percent: int
    modules: list[CampaignReportModuleCell]


class AdministratorCampaignReport(BaseModel):
    campaign_id: uuid.UUID
    campaign_name: str
    status: str
    due_date: date | None
    modules: list[CampaignReportModule]
    learners: list[CampaignReportLearner]
