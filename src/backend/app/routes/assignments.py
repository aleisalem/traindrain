"""Assignment: who has to read a module, and by when.

Two audiences, one boundary. Any Content Manager or Administrator may assign a
module to a *group*; only an Administrator may name an *individual* — the
data-minimization line the PRD draws so that authoring a module never
requires touching the staff directory. `GET /api/content/groups` exists for
the same reason: it is the one view of groups a Content Manager needs, and it
never carries a member list.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.access import is_administrator
from app.core.config import get_settings
from app.db import get_db
from app.dependencies import get_module_or_404, get_ses_client, require_content_manager
from app.models import Assignment, Group, User, group_members
from app.schemas.assignments import (
    AssignmentCreateRequest,
    AssignmentResponse,
    AssignmentTarget,
    ContentGroupResponse,
)
from app.schemas.modules import ModuleActor
from app.security.audit import record_audit_log
from app.security.mailer import SESClient, send_assignment_email

router = APIRouter(prefix="/api/content", tags=["assignments"])

_ASSIGNMENT_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found."
)


def _require_administrator_for_individual(user: User, target_type: str) -> None:
    """The one line a Content Manager may not cross: naming a person.

    Group assignment stays open to both roles — a Content Manager's whole job
    is deciding who reads what, and a group is the unit the PRD gives them for
    that. An individual is different: reaching one by id is reaching into the
    user directory, which a Content Manager never otherwise touches.
    """
    if target_type == "user" and not is_administrator(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only an Administrator may assign a module to an individual.",
        )


async def _resolve_target_name(
    db: AsyncSession, assignment: Assignment, *, reveal_user_identity: bool
) -> str | None:
    if assignment.target_type == "group":
        group = await db.get(Group, assignment.target_id)
        return group.name if group else None
    if not reveal_user_identity:
        return None
    user = await db.get(User, assignment.target_id)
    return ModuleActor.from_user(user).display_name if user else None


async def _to_assignment_response(
    db: AsyncSession, assignment: Assignment, *, caller: User
) -> AssignmentResponse:
    name = await _resolve_target_name(
        db, assignment, reveal_user_identity=is_administrator(caller)
    )
    assigner = await db.get(User, assignment.assigned_by)
    return AssignmentResponse(
        id=assignment.id,
        translation_group_id=assignment.translation_group_id,
        target=AssignmentTarget(type=assignment.target_type, id=assignment.target_id, name=name),
        due_date=assignment.due_date,
        requirement=assignment.requirement,
        auto_reminders=assignment.auto_reminders,
        assigned_by=ModuleActor.from_user(assigner),
        created_at=assignment.created_at,
    )


@router.get("/modules/{module_id}/assignments", response_model=list[AssignmentResponse])
async def list_assignments(
    module_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    caller: User = Depends(require_content_manager),
) -> list[AssignmentResponse]:
    """Who this module's *material* is assigned to.

    Scoped to the translation group, not the one variant in the URL: an
    assignment always targets the group, so any of its language variants shows
    the same list.
    """
    module = await get_module_or_404(db, module_id)
    assignments = list(
        (
            await db.execute(
                select(Assignment)
                .where(Assignment.translation_group_id == module.translation_group_id)
                .order_by(Assignment.created_at)
            )
        ).scalars()
    )
    return [await _to_assignment_response(db, assignment, caller=caller) for assignment in assignments]


async def _targeted_learners(db: AsyncSession, payload: AssignmentCreateRequest) -> list[User]:
    """Who is targeted right now, so they can be emailed once, at creation.

    Membership is never expanded into the assignment row itself (see
    `Assignment`'s docstring) — this is only for the one-time notification,
    not for what a learner's list resolves against later.
    """
    if payload.target_type == "group":
        group = await db.get(Group, payload.target_id)
        if group is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found.")
        return list(
            (
                await db.execute(
                    select(User).join(group_members, group_members.c.user_id == User.id).where(
                        group_members.c.group_id == group.id
                    )
                )
            ).scalars()
        )

    target_user = await db.get(User, payload.target_id)
    if target_user is None or target_user.erased_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    return [target_user]


@router.post(
    "/modules/{module_id}/assignments",
    response_model=AssignmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_assignment(
    module_id: uuid.UUID,
    payload: AssignmentCreateRequest,
    db: AsyncSession = Depends(get_db),
    caller: User = Depends(require_content_manager),
    ses_client: SESClient = Depends(get_ses_client),
) -> AssignmentResponse:
    """Assign a module's material to a group or (Administrator only) a person.

    Every currently-targeted learner is emailed once, here, in their own
    language. Someone who joins the targeted group later is not emailed
    retroactively — they simply see the module on their next visit, because
    membership is resolved at read time rather than expanded into rows now.
    """
    _require_administrator_for_individual(caller, payload.target_type)
    module = await get_module_or_404(db, module_id)
    targeted_learners = await _targeted_learners(db, payload)

    assignment = Assignment(
        translation_group_id=module.translation_group_id,
        target_type=payload.target_type,
        target_id=payload.target_id,
        due_date=payload.due_date,
        requirement=payload.requirement,
        auto_reminders=payload.auto_reminders,
        assigned_by=caller.id,
    )
    db.add(assignment)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "already_assigned",
                "message": "This module is already assigned to this target.",
            },
        ) from exc

    await record_audit_log(
        db,
        actor_user_id=caller.id,
        action="assignment_created",
        detail={
            "assignment_id": str(assignment.id),
            "translation_group_id": str(module.translation_group_id),
            "module_title": module.title,
            "target_type": payload.target_type,
            "target_id": str(payload.target_id),
            "requirement": payload.requirement,
            "due_date": payload.due_date.isoformat() if payload.due_date else None,
        },
    )

    module_url = f"{get_settings().frontend_base_url}/modules/{module.translation_group_id}"
    for learner in targeted_learners:
        if learner.disabled_at is not None or learner.erased_at is not None:
            continue
        await send_assignment_email(
            ses_client,
            to_email=learner.email,
            language=learner.preferred_language or "en",
            module_title=module.title,
            due_date=payload.due_date,
            module_url=module_url,
        )

    # Committed only after every email attempt succeeds, matching the invite
    # pattern: a failed send leaves no half-issued assignment behind to retry
    # around.
    await db.commit()
    return await _to_assignment_response(db, assignment, caller=caller)


@router.delete("/assignments/{assignment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_assignment(
    assignment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    caller: User = Depends(require_content_manager),
) -> None:
    """Remove an assignment. Never touches progress — completion is the
    learner's, earned independently of whatever told them to start."""
    assignment = await db.get(Assignment, assignment_id)
    if assignment is None:
        raise _ASSIGNMENT_NOT_FOUND
    _require_administrator_for_individual(caller, assignment.target_type)

    detail: dict[str, Any] = {
        "assignment_id": str(assignment.id),
        "translation_group_id": str(assignment.translation_group_id),
        "target_type": assignment.target_type,
    }
    await db.delete(assignment)
    await record_audit_log(db, actor_user_id=caller.id, action="assignment_removed", detail=detail)
    await db.commit()


@router.get("/groups", response_model=list[ContentGroupResponse])
async def list_content_groups(
    db: AsyncSession = Depends(get_db),
    caller: User = Depends(require_content_manager),
) -> list[ContentGroupResponse]:
    """Group names, descriptions, and member counts — and nothing else.

    Exists so a Content Manager assigning a module never has a reason to call
    `/api/admin/groups/{id}/members`, which is the actual member list.
    """
    rows = await db.execute(
        select(Group.id, Group.name, Group.description, func.count(group_members.c.user_id))
        .outerjoin(group_members, group_members.c.group_id == Group.id)
        .group_by(Group.id)
        .order_by(Group.name)
    )
    return [
        ContentGroupResponse(id=row[0], name=row[1], description=row[2], member_count=row[3])
        for row in rows
    ]
