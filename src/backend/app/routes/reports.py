"""Reporting: did people do the training?

The response shape differs by role on the server, not the client — a request
made with the same URL and the same cookie by a Content Manager and by an
Administrator gets two different Pydantic models back
(`ContentManagerModuleReport` vs. `AdministratorModuleReport`), decided by
`is_administrator(caller)` and nothing the caller supplies. The CSV export is a
second, Administrator-only route rather than a format flag on the same one,
so the 403 boundary is a route-level `Depends`, not a branch inside a shared
handler that a review could miss.
"""

import csv
import io
import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.access import is_administrator
from app.db import get_db
from app.dependencies import get_module_or_404, require_administrator, require_content_manager
from app.models import User
from app.reporting import LearnerStanding, full_roster, group_standings
from app.schemas.modules import ModuleActor
from app.schemas.reports import (
    AdministratorModuleReport,
    ContentManagerModuleReport,
    ModuleReportGroupSummary,
    ModuleReportLearner,
)
from app.security.system_settings import deployment_today

router = APIRouter(prefix="/api/content", tags=["reports"])


def _to_learner_row(standing: LearnerStanding) -> ModuleReportLearner:
    return ModuleReportLearner(
        user_id=standing.user.id,
        name=ModuleActor.from_user(standing.user).display_name,
        email=standing.user.email,
        state=standing.state,
        overdue=standing.overdue,
        due_date=standing.due_date,
        completed_at=standing.completed_at,
        completed_version_number=standing.completed_version_number,
    )


@router.get("/modules/{module_id}/report", response_model=None)
async def get_module_report(
    module_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    caller: User = Depends(require_content_manager),
) -> AdministratorModuleReport | ContentManagerModuleReport:
    """Did this module's material land?

    A Content Manager gets `ContentManagerModuleReport` — per-group counts,
    never a name. An Administrator gets `AdministratorModuleReport` — the full
    roster, because answering an auditor's "who hasn't done it yet" is
    precisely what the Administrator role exists to do without a UI-level
    workaround. `response_model=None` is deliberate: FastAPI serializes
    whichever of the two models this function actually returns, rather than
    filtering both through one shared schema that would have to be the union's
    lowest common denominator.
    """
    module = await get_module_or_404(db, module_id)
    today = await deployment_today(db)

    if is_administrator(caller):
        learners = await full_roster(db, module.translation_group_id, today=today)
        return AdministratorModuleReport(
            translation_group_id=module.translation_group_id,
            learners=[_to_learner_row(standing) for standing in learners],
        )

    groups = await group_standings(db, module.translation_group_id, today=today)
    return ContentManagerModuleReport(
        translation_group_id=module.translation_group_id,
        groups=[
            ModuleReportGroupSummary(
                group_id=group.id,
                group_name=group.name,
                member_count=len(standings),
                completed=sum(1 for s in standings if s.state == "completed"),
                in_progress=sum(1 for s in standings if s.state == "in_progress"),
                not_started=sum(1 for s in standings if s.state == "not_started"),
                overdue=sum(1 for s in standings if s.overdue),
            )
            for group, standings in groups
        ],
    )


@router.get("/modules/{module_id}/report.csv")
async def get_module_report_csv(
    module_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_administrator),
) -> Response:
    """The Administrator roster as a file to hand an auditor.

    Administrator-only, on its own route rather than a format switch on
    `get_module_report` — a Content Manager must get a flat 403 here, never a
    branch that has to remember to withhold names for this one format too.
    """
    module = await get_module_or_404(db, module_id)
    today = await deployment_today(db)
    learners = await full_roster(db, module.translation_group_id, today=today)

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        ["Name", "Email", "Status", "Completed At", "Completed Version", "Due Date", "Overdue"]
    )
    for standing in learners:
        writer.writerow(
            [
                ModuleActor.from_user(standing.user).display_name,
                standing.user.email,
                standing.state,
                standing.completed_at.isoformat() if standing.completed_at else "",
                standing.completed_version_number if standing.completed_version_number else "",
                standing.due_date.isoformat() if standing.due_date else "",
                "yes" if standing.overdue else "no",
            ]
        )

    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="module-{module_id}-report.csv"'
        },
    )
