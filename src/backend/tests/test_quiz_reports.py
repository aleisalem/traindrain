"""Quiz reports (Release 2, ticket 13).

What is held down: group-level pass rate, average score and attempts-to-pass for
a Content Manager with no names; per-question percent-correct; best score and
attempt count for an Administrator only; no individual answer in any response or
CSV; and the figures surviving a user erase.
"""

import csv
import io
from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from tests.test_assignments import _add_to_group, _make_group, _make_user_with_role
from tests.test_learner_viewer import _login, _login_with_role
from tests.test_quiz_taking import Quiz, _publish_quiz_module, _ready, _take
from tests.test_reports import _assign_to_group, _setup_three_learner_group


async def _learner_takes(
    client: AsyncClient,
    db_session: AsyncSession,
    quiz: Quiz,
    group: Any,
    *,
    email: str,
    attempts: list[set[str]],
) -> User:
    """A group member reads the module and submits one attempt per entry, each
    answering the named questions rightly and the rest wrongly."""
    user = await _make_user_with_role(db_session, email=email, role_name="Learner")
    await _add_to_group(db_session, user, group)
    await _login(client, email=email)
    await _ready(client, quiz)
    for right in attempts:
        await _take(client, quiz, quiz.answers(right=right))
    return user


ALL = {"Single?", "Multi?", "Bool?"}


async def _scenario(
    client: AsyncClient, db_session: AsyncSession, slug: str
) -> dict[str, Any]:
    quiz = await _publish_quiz_module(client, db_session, slug)
    group = await _make_group(db_session, name=f"{slug} group")
    await _login(client, email=f"{slug}-author@example.com")
    await _assign_to_group(client, module_id=quiz.module_id, group_id=str(group.id))
    # A fails everything, then passes; B fails after getting one question right.
    a = await _learner_takes(
        client, db_session, quiz, group, email=f"{slug}-a@example.com", attempts=[set(), ALL]
    )
    b = await _learner_takes(
        client, db_session, quiz, group, email=f"{slug}-b@example.com", attempts=[{"Single?"}]
    )
    c = await _learner_takes(
        client, db_session, quiz, group, email=f"{slug}-c@example.com", attempts=[ALL]
    )
    return {"quiz": quiz, "group": group, "a": a, "b": b, "c": c, "slug": slug}


async def _report(client: AsyncClient, quiz: Quiz) -> Any:
    return await client.get(f"/api/content/modules/{quiz.module_id}/report")


async def test_content_manager_sees_group_quiz_statistics_and_no_identities(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    s = await _scenario(client, db_session, "qr1")
    await _login_with_role(
        client, db_session, email="qr1-cm@example.com", role_name="Content Manager"
    )
    response = await _report(client, s["quiz"])
    assert response.status_code == 200, response.text
    body = response.json()

    (group,) = body["groups"]
    assert group["quiz"] == {
        "attempted": 3,
        "passed": 2,
        "pass_rate_percent": 67,
        "average_score_percent": 58,  # (0 + 100 + 33 + 100) / 4
        "average_attempts_to_pass": 1.5,  # A passed on the 2nd attempt, C on the 1st
    }
    assert body["quiz"]["pass_mark_percent"] == 80
    assert body["quiz"]["attempts"] == 4
    assert body["quiz"]["overall"]["passed"] == 2

    for email in ("qr1-a@example.com", "qr1-b@example.com", "qr1-c@example.com"):
        assert email not in response.text
    for forbidden in ("best_score_percent", "attempt_count", "option_ids", '"answers"', "is_correct"):
        assert forbidden not in response.text


async def test_per_question_percent_correct(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    s = await _scenario(client, db_session, "qr2")
    await _login_with_role(
        client, db_session, email="qr2-cm@example.com", role_name="Content Manager"
    )
    questions = (await _report(client, s["quiz"])).json()["quiz"]["questions"]
    by_prompt = {q["prompt_text"]: q for q in questions}
    # A: wrong, right. B: Single right, others wrong. C: all right.
    assert by_prompt["Single?"]["percent_correct"] == 75
    assert by_prompt["Multi?"]["percent_correct"] == 50
    assert by_prompt["Bool?"]["percent_correct"] == 50
    assert by_prompt["Single?"]["answered"] == 4
    assert [q["position"] for q in questions] == sorted(q["position"] for q in questions)


async def test_administrator_roster_has_best_score_and_attempts_but_no_answers(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    s = await _scenario(client, db_session, "qr3")
    await _login_with_role(
        client, db_session, email="qr3-admin@example.com", role_name="Administrator"
    )
    response = await _report(client, s["quiz"])
    assert response.status_code == 200
    rows = {row["email"]: row for row in response.json()["learners"]}
    assert (rows["qr3-a@example.com"]["best_score_percent"], rows["qr3-a@example.com"]["attempt_count"]) == (100, 2)
    assert (rows["qr3-b@example.com"]["best_score_percent"], rows["qr3-b@example.com"]["attempt_count"]) == (33, 1)
    for forbidden in ("option_ids", '"answers"', "is_correct", "question_results"):
        assert forbidden not in response.text

    exported = await client.get(f"/api/content/modules/{s['quiz'].module_id}/report.csv")
    assert exported.status_code == 200
    table = list(csv.DictReader(io.StringIO(exported.text)))
    by_email = {row["Email"]: row for row in table}
    assert by_email["qr3-a@example.com"]["Best Quiz Score %"] == "100"
    assert by_email["qr3-a@example.com"]["Quiz Attempts"] == "2"
    assert by_email["qr3-b@example.com"]["Quiz Attempts"] == "1"
    assert "option" not in exported.text.lower()


async def test_csv_stays_administrator_only(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    s = await _scenario(client, db_session, "qr4")
    await _login_with_role(
        client, db_session, email="qr4-cm@example.com", role_name="Content Manager"
    )
    assert (
        await client.get(f"/api/content/modules/{s['quiz'].module_id}/report.csv")
    ).status_code == 403


async def test_statistics_stay_correct_after_a_user_erase(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    s = await _scenario(client, db_session, "qr5")
    await _login_with_role(
        client, db_session, email="qr5-admin@example.com", role_name="Administrator"
    )
    before = (await _report(client, s["quiz"])).json()["quiz"]
    assert (await client.post(f"/api/admin/users/{s['c'].id}/erase")).status_code == 204

    after = await _report(client, s["quiz"])
    assert after.json()["quiz"] == before  # the erased learner's attempt still counts
    assert "qr5-c@example.com" not in after.text
    assert all(row["user_id"] != str(s["c"].id) for row in after.json()["learners"])


async def test_a_module_without_a_quiz_has_no_quiz_section(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    setup = await _setup_three_learner_group(client, db_session, prefix="qr6")
    await _login(client, email="qr6-cm@example.com")
    response = await client.get(f"/api/content/modules/{setup['module']['id']}/report")
    assert response.status_code == 200
    body = response.json()
    assert body["quiz"] is None
    assert all(group["quiz"] is None for group in body["groups"])
