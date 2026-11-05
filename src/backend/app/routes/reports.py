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
from app.reporting import (
    LearnerStanding,
    campaign_full_roster,
    campaign_group_standings,
    full_roster,
    group_standings,
)
from app.schemas.modules import ModuleActor
from app.schemas.reports import (
    AdministratorCampaignReport,
    AdministratorModuleReport,
    CampaignReportGroupSummary,
    CampaignReportLearner,
    CampaignReportModule,
    CampaignReportModuleCell,
    ContentManagerCampaignReport,
    ContentManagerModuleReport,
    ModuleReportGroupSummary,
    ModuleReportLearner,
)
from app.security.system_settings import deployment_today
from app.routes.campaigns import _get_campaign_or_404, _module_responses
from app.models import Campaign

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
        learners = await full_roster(
            db,
            module.translation_group_id,
            today=today,
            include_unassigned_progress=module.status == "deleted",
            include_quiz_attempters=True,
        )
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
    learners = await full_roster(
        db,
        module.translation_group_id,
        today=today,
        include_unassigned_progress=module.status == "deleted",
        include_quiz_attempters=True,
    )

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


# --- Campaign reports ---------------------------------------------------------
#
# "Did people do this programme?" Visibility is `may_see_campaign` — exactly
# the people who may edit it — so a non-participant gets the same 404 every
# other campaign route gives.


async def _campaign_modules(db: AsyncSession, campaign: Campaign) -> list[CampaignReportModule]:
    return [
        CampaignReportModule(
            translation_group_id=m.translation_group_id,
            title=m.title,
            requirement=m.requirement,
            unavailable=m.availability == "deleted",
        )
        for m in await _module_responses(db, campaign)
    ]


async def _administrator_campaign_report(
    db: AsyncSession, campaign: Campaign
) -> AdministratorCampaignReport:
    today = await deployment_today(db)
    standings = await campaign_full_roster(db, campaign, today=today)
    return AdministratorCampaignReport(
        campaign_id=campaign.id,
        campaign_name=campaign.name,
        status=campaign.status,
        due_date=campaign.due_date,
        modules=await _campaign_modules(db, campaign),
        learners=[
            CampaignReportLearner(
                user_id=s.user.id,
                name=ModuleActor.from_user(s.user).display_name,
                email=s.user.email,
                state=s.state,
                overdue=s.overdue,
                required_total=s.required_total,
                required_done=s.required_done,
                progress_percent=s.progress_percent,
                modules=[
                    CampaignReportModuleCell(
                        translation_group_id=c.translation_group_id,
                        requirement=c.requirement,
                        state=c.state,
                        unavailable=c.unavailable,
                        completed_at=c.completed_at,
                        completed_version_number=c.completed_version_number,
                    )
                    for c in s.cells
                ],
            )
            for s in standings
        ],
    )


@router.get("/campaigns/{campaign_id}/report", response_model=None)
async def get_campaign_report(
    campaign_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    caller: User = Depends(require_content_manager),
) -> AdministratorCampaignReport | ContentManagerCampaignReport:
    """Per-group counts for a Content Manager, the per-learner roster for an
    Administrator — the shape is decided here, never by the client."""
    campaign = await _get_campaign_or_404(db, campaign_id, caller)
    if is_administrator(caller):
        return await _administrator_campaign_report(db, campaign)

    today = await deployment_today(db)
    summaries = []
    for group, standings in await campaign_group_standings(db, campaign, today=today):
        total = len(standings)
        summaries.append(
            CampaignReportGroupSummary(
                group_id=group.id,
                group_name=group.name,
                member_count=total,
                completed=sum(1 for s in standings if s.state == "completed"),
                in_progress=sum(1 for s in standings if s.state == "in_progress"),
                not_started=sum(1 for s in standings if s.state == "not_started"),
                overdue=sum(1 for s in standings if s.overdue),
                suspended=sum(1 for s in standings if s.state == "suspended"),
                average_progress=(
                    round(sum(s.progress_percent for s in standings) / total) if total else 0
                ),
            )
        )
    return ContentManagerCampaignReport(
        campaign_id=campaign.id,
        campaign_name=campaign.name,
        status=campaign.status,
        due_date=campaign.due_date,
        modules=await _campaign_modules(db, campaign),
        groups=summaries,
    )


@router.get("/campaigns/{campaign_id}/report.csv")
async def get_campaign_report_csv(
    campaign_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_administrator),
) -> Response:
    """The roster as a file: one row per learner, one column per module."""
    campaign = await _get_campaign_or_404(db, campaign_id, admin)
    report = await _administrator_campaign_report(db, campaign)
    titles = {m.translation_group_id: (m.title or "") for m in report.modules}

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    first = report.learners[0].modules if report.learners else []
    module_columns = [
        (c.translation_group_id, titles.get(c.translation_group_id, "")) for c in first
    ] or [(m.translation_group_id, m.title or "") for m in report.modules]
    writer.writerow(
        ["Name", "Email", "Status", "Overdue", "Required Done", "Required Total", "Progress %"]
        + [_csv_safe(title) for _, title in module_columns]
    )
    for learner in report.learners:
        cells = {c.translation_group_id: c for c in learner.modules}
        writer.writerow(
            [
                _csv_safe(learner.name),
                _csv_safe(learner.email),
                learner.state,
                "yes" if learner.overdue else "no",
                learner.required_done,
                learner.required_total,
                learner.progress_percent,
            ]
            + [
                cells[g].state if g in cells else ""
                for g, _ in module_columns
            ]
        )
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="campaign-{campaign_id}-report.csv"'
        },
    )


def _csv_safe(value: str) -> str:
    """Neutralize spreadsheet formula injection in user-supplied text."""
    return "'" + value if value[:1] in ("=", "+", "-", "@", "\t", "\r") else value
