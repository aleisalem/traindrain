"""Campaign drafts: the programme a Content Manager builds before anyone sees it.

`created_by` and `status` appear only in responses; `extra="forbid"` turns an
attempt to send either into a 422, as it does for modules.
"""

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.assignments import Requirement, TargetType
from app.schemas.modules import ModuleActor

CampaignStatus = Literal["draft", "active", "suspended", "closed"]

# Whether a module can be read by learners right now. Reported per module so an
# author sees what to fix before activating; a draft may reference any of them.
ModuleAvailability = Literal["published", "unpublished", "deleted"]

MAX_CAMPAIGN_MODULES = 100
MAX_CAMPAIGN_TARGETS = 200


class CampaignModuleInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    translation_group_id: uuid.UUID
    requirement: Requirement


class CampaignTargetInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: TargetType
    id: uuid.UUID


def _check_unique_modules(modules: list[CampaignModuleInput] | None) -> None:
    if modules is None:
        return
    ids = [module.translation_group_id for module in modules]
    if len(ids) != len(set(ids)):
        raise ValueError("A module may appear in a campaign only once.")


def _check_unique_targets(targets: list[CampaignTargetInput] | None) -> None:
    if targets is None:
        return
    keys = [(target.type, target.id) for target in targets]
    if len(keys) != len(set(keys)):
        raise ValueError("A target may appear in a campaign only once.")


class CampaignCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    start_date: date | None = None
    due_date: date | None = None
    # Defaults on, as for assignments: chasing a deadline is a meaningful
    # choice but not one that needs forcing an explicit answer.
    auto_reminders: bool = True
    sequential: bool = False
    modules: list[CampaignModuleInput] = Field(default_factory=list, max_length=MAX_CAMPAIGN_MODULES)
    targets: list[CampaignTargetInput] = Field(default_factory=list, max_length=MAX_CAMPAIGN_TARGETS)

    @model_validator(mode="after")
    def _validate(self) -> "CampaignCreateRequest":
        _check_unique_modules(self.modules)
        _check_unique_targets(self.targets)
        if self.start_date and self.due_date and self.due_date < self.start_date:
            raise ValueError("The due date cannot be before the start date.")
        return self


class CampaignUpdateRequest(BaseModel):
    """A partial update. `modules` and `targets`, when present, are full
    replacements — the list order is the module order — and a date set to
    `null` clears it.
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    start_date: date | None = None
    due_date: date | None = None
    auto_reminders: bool | None = None
    sequential: bool | None = None
    modules: list[CampaignModuleInput] | None = Field(default=None, max_length=MAX_CAMPAIGN_MODULES)
    targets: list[CampaignTargetInput] | None = Field(default=None, max_length=MAX_CAMPAIGN_TARGETS)

    @model_validator(mode="after")
    def _validate(self) -> "CampaignUpdateRequest":
        _check_unique_modules(self.modules)
        _check_unique_targets(self.targets)
        for field in ("name", "auto_reminders", "sequential", "modules", "targets"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null.")
        return self


class CampaignModuleResponse(BaseModel):
    translation_group_id: uuid.UUID
    position: int
    requirement: Requirement
    title: str | None
    availability: ModuleAvailability


class CampaignTargetResponse(BaseModel):
    type: TargetType
    id: uuid.UUID
    # A group's name is always shown; a person's only to an Administrator, so
    # building a campaign never reaches into the staff directory.
    name: str | None


class CampaignSummaryResponse(BaseModel):
    id: uuid.UUID
    name: str
    status: CampaignStatus
    start_date: date | None
    due_date: date | None
    module_count: int
    target_count: int
    created_at: datetime
    updated_at: datetime


class CampaignResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    status: CampaignStatus
    sequential: bool
    auto_reminders: bool
    start_date: date | None
    due_date: date | None
    created_by: ModuleActor
    modules: list[CampaignModuleResponse]
    targets: list[CampaignTargetResponse]
    created_at: datetime
    updated_at: datetime
