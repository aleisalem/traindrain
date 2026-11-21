"""Quiz results for the module report — statistics only, never an answer.

Everything here is read from the columns that survive a user erase
(`score_percent`, `passed`, `question_results`, `version_id`, `submitted_at`);
`QuizAttempt.answers` is never selected, so no individual answer can reach a
report or CSV by construction. An erased learner's attempts keep counting in
the module-wide figures (they sit against the tombstone), while the per-group
figures follow live membership like every other count in the report.
"""

import uuid
from collections.abc import Collection
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content.validation import extract_search_text
from app.models import Module, ModuleVersion, QuizAttempt
from app.quiz_attempts import snapshot_quiz
from app.schemas.reports import QuizGroupStats, QuizQuestionStat, QuizReport


@dataclass
class LearnerQuizStats:
    scores: list[int] = field(default_factory=list)
    attempts_to_pass: int | None = None

    @property
    def attempts(self) -> int:
        return len(self.scores)

    @property
    def best(self) -> int | None:
        return max(self.scores) if self.scores else None


@dataclass
class _Row:
    user_id: uuid.UUID
    version_id: uuid.UUID
    score: int
    passed: bool
    results: dict[str, bool]


async def _submitted_rows(db: AsyncSession, group_id: uuid.UUID) -> list[_Row]:
    rows = (
        await db.execute(
            select(
                QuizAttempt.user_id,
                QuizAttempt.version_id,
                QuizAttempt.score_percent,
                QuizAttempt.passed,
                QuizAttempt.question_results,
            )
            .where(
                QuizAttempt.translation_group_id == group_id,
                QuizAttempt.submitted_at.is_not(None),
            )
            .order_by(QuizAttempt.submitted_at)
        )
    ).all()
    return [_Row(r[0], r[1], r[2] or 0, bool(r[3]), r[4] or {}) for r in rows]


def _per_learner(rows: list[_Row]) -> dict[uuid.UUID, LearnerQuizStats]:
    stats: dict[uuid.UUID, LearnerQuizStats] = {}
    for row in rows:
        entry = stats.setdefault(row.user_id, LearnerQuizStats())
        entry.scores.append(row.score)
        if row.passed and entry.attempts_to_pass is None:
            entry.attempts_to_pass = entry.attempts
    return stats


def group_stats(
    per_learner: dict[uuid.UUID, LearnerQuizStats], member_ids: Collection[uuid.UUID]
) -> QuizGroupStats:
    members = [per_learner[m] for m in member_ids if m in per_learner]
    passers = [m for m in members if m.attempts_to_pass is not None]
    scores = [s for m in members for s in m.scores]
    return QuizGroupStats(
        attempted=len(members),
        passed=len(passers),
        pass_rate_percent=round(100 * len(passers) / len(members)) if members else None,
        average_score_percent=round(sum(scores) / len(scores)) if scores else None,
        average_attempts_to_pass=(
            round(sum(m.attempts_to_pass or 0 for m in passers) / len(passers), 1)
            if passers
            else None
        ),
    )


@dataclass
class QuizFacts:
    """What the quiz report needs, fetched once per request."""

    report: QuizReport
    per_learner: dict[uuid.UUID, LearnerQuizStats]


async def quiz_facts(db: AsyncSession, module: Module) -> QuizFacts | None:
    """None when the module has no published quiz — the report then has no quiz
    section at all."""
    if module.current_version_id is None:
        return None
    version = await db.get(ModuleVersion, module.current_version_id)
    quiz: dict[str, Any] | None = snapshot_quiz(version) if version else None
    if quiz is None:
        return None

    rows = await _submitted_rows(db, module.translation_group_id)
    per_learner = _per_learner(rows)

    current = [r for r in rows if r.version_id == module.current_version_id]
    questions: list[QuizQuestionStat] = []
    for question in sorted(quiz["questions"], key=lambda q: q["position"]):
        answered = [r for r in current if question["id"] in r.results]
        correct = sum(1 for r in answered if r.results[question["id"]])
        questions.append(
            QuizQuestionStat(
                question_id=uuid.UUID(question["id"]),
                position=question["position"],
                prompt_text=extract_search_text(question["prompt"]),
                answered=len(answered),
                correct=correct,
                percent_correct=round(100 * correct / len(answered)) if answered else None,
            )
        )

    everyone = group_stats(per_learner, per_learner.keys())
    return QuizFacts(
        report=QuizReport(
            pass_mark_percent=quiz["pass_mark_percent"],
            attempts=len(rows),
            overall=everyone,
            questions=questions,
        ),
        per_learner=per_learner,
    )
