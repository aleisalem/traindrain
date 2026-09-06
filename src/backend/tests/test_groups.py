import re
import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, Group, Role, User
from app.security.passwords import hash_password
from app.security.sessions import COOKIE_NAME

KNOWN_PASSWORD = "a-perfectly-fine-passphrase"


async def _make_user_with_role(db_session: AsyncSession, *, email: str, role_name: str) -> User:
    role = (await db_session.execute(select(Role).where(Role.name == role_name))).scalar_one()
    user = User(
        id=uuid.uuid4(),
        email=email,
        password_hash=hash_password(KNOWN_PASSWORD),
        roles=[role],
    )
    db_session.add(user)
    await db_session.commit()
    return user


async def _login(client: AsyncClient, *, email: str) -> None:
    response = await client.post(
        "/api/auth/login", json={"email": email, "password": KNOWN_PASSWORD}
    )
    client.cookies.set(COOKIE_NAME, response.cookies[COOKIE_NAME])


async def _login_as_admin(client: AsyncClient, db_session: AsyncSession, *, email: str) -> User:
    admin = await _make_user_with_role(db_session, email=email, role_name="Administrator")
    await _login(client, email=email)
    return admin


async def _make_group(db_session: AsyncSession, *, name: str, description: str | None = None) -> Group:
    group = Group(name=name, description=description)
    db_session.add(group)
    await db_session.commit()
    return group


def _latest_invite_token(sent_emails: list[dict[str, Any]]) -> str:
    body = sent_emails[-1]["Message"]["Body"]["Text"]["Data"]
    match = re.search(r"token=(\S+)", body)
    assert match is not None
    return match.group(1)


# --- Group CRUD ---


async def test_admin_can_create_a_group(client: AsyncClient, db_session: AsyncSession) -> None:
    await _login_as_admin(client, db_session, email="admin-group-create@example.com")

    response = await client.post(
        "/api/admin/groups", json={"name": "Sales Team", "description": "All sales reps"}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Sales Team"
    assert body["description"] == "All sales reps"

    audit_entry = (
        await db_session.execute(select(AuditLog).where(AuditLog.action == "group_created"))
    ).scalar_one()
    assert audit_entry.detail["name"] == "Sales Team"


async def test_creating_a_group_with_a_duplicate_name_is_a_conflict(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_as_admin(client, db_session, email="admin-group-dup@example.com")
    await _make_group(db_session, name="Engineering")

    response = await client.post("/api/admin/groups", json={"name": "Engineering"})

    assert response.status_code == 409


async def test_non_admin_is_forbidden_from_creating_a_group(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user_with_role(db_session, email="learner-group-create@example.com", role_name="Learner")
    await _login(client, email="learner-group-create@example.com")

    response = await client.post("/api/admin/groups", json={"name": "Sneaky Group"})

    assert response.status_code == 403


async def test_admin_can_list_groups(client: AsyncClient, db_session: AsyncSession) -> None:
    await _login_as_admin(client, db_session, email="admin-group-list@example.com")
    await _make_group(db_session, name="Marketing")

    response = await client.get("/api/admin/groups")

    assert response.status_code == 200
    names = {group["name"] for group in response.json()}
    assert "Marketing" in names


async def test_non_admin_is_forbidden_from_listing_groups(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user_with_role(db_session, email="learner-group-list@example.com", role_name="Learner")
    await _login(client, email="learner-group-list@example.com")

    response = await client.get("/api/admin/groups")

    assert response.status_code == 403


async def test_admin_can_update_a_group(client: AsyncClient, db_session: AsyncSession) -> None:
    await _login_as_admin(client, db_session, email="admin-group-update@example.com")
    group = await _make_group(db_session, name="Old Name", description="Old description")

    response = await client.put(
        f"/api/admin/groups/{group.id}",
        json={"name": "New Name", "description": "New description"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "New Name"
    assert body["description"] == "New description"

    audit_entry = (
        await db_session.execute(select(AuditLog).where(AuditLog.action == "group_updated"))
    ).scalar_one()
    assert audit_entry.detail["name"] == "New Name"


async def test_updating_a_group_to_a_duplicate_name_is_a_conflict(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_as_admin(client, db_session, email="admin-group-update-dup@example.com")
    await _make_group(db_session, name="Taken Name")
    group = await _make_group(db_session, name="Available Name")

    response = await client.put(
        f"/api/admin/groups/{group.id}", json={"name": "Taken Name"}
    )

    assert response.status_code == 409


async def test_updating_an_unknown_group_is_not_found(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_as_admin(client, db_session, email="admin-group-update-unknown@example.com")

    response = await client.put(
        f"/api/admin/groups/{uuid.uuid4()}", json={"name": "Doesn't matter"}
    )

    assert response.status_code == 404


async def test_non_admin_is_forbidden_from_updating_a_group(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user_with_role(db_session, email="learner-group-update@example.com", role_name="Learner")
    group = await _make_group(db_session, name="Protected Update Group")
    await _login(client, email="learner-group-update@example.com")

    response = await client.put(f"/api/admin/groups/{group.id}", json={"name": "Renamed"})

    assert response.status_code == 403


async def test_admin_can_delete_a_group(client: AsyncClient, db_session: AsyncSession) -> None:
    await _login_as_admin(client, db_session, email="admin-group-delete@example.com")
    group = await _make_group(db_session, name="To Delete")

    response = await client.delete(f"/api/admin/groups/{group.id}")

    assert response.status_code == 204
    assert await db_session.get(Group, group.id) is None

    audit_entry = (
        await db_session.execute(select(AuditLog).where(AuditLog.action == "group_deleted"))
    ).scalar_one()
    assert audit_entry.detail["name"] == "To Delete"


async def test_deleting_a_group_removes_membership_rows(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_as_admin(client, db_session, email="admin-group-delete-members@example.com")
    group = await _make_group(db_session, name="Has Members")
    member = await _make_user_with_role(
        db_session, email="member-of-deleted-group@example.com", role_name="Learner"
    )
    await client.post(f"/api/admin/groups/{group.id}/members/{member.id}")

    response = await client.delete(f"/api/admin/groups/{group.id}")

    assert response.status_code == 204
    await db_session.refresh(member, attribute_names=["groups"])
    assert member.groups == []


async def test_deleting_an_unknown_group_is_not_found(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_as_admin(client, db_session, email="admin-group-delete-unknown@example.com")

    response = await client.delete(f"/api/admin/groups/{uuid.uuid4()}")

    assert response.status_code == 404


async def test_non_admin_is_forbidden_from_deleting_a_group(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user_with_role(db_session, email="learner-group-delete@example.com", role_name="Learner")
    group = await _make_group(db_session, name="Protected Group")
    await _login(client, email="learner-group-delete@example.com")

    response = await client.delete(f"/api/admin/groups/{group.id}")

    assert response.status_code == 403


# --- Membership ---


async def test_admin_can_view_a_groups_members(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_as_admin(client, db_session, email="admin-group-members@example.com")
    group = await _make_group(db_session, name="Viewable Group")
    member = await _make_user_with_role(
        db_session, email="viewable-member@example.com", role_name="Learner"
    )
    await _make_user_with_role(
        db_session, email="non-member@example.com", role_name="Learner"
    )
    await client.post(f"/api/admin/groups/{group.id}/members/{member.id}")

    response = await client.get(f"/api/admin/groups/{group.id}/members")

    assert response.status_code == 200
    emails = {row["email"] for row in response.json()}
    assert "viewable-member@example.com" in emails
    assert "non-member@example.com" not in emails


async def test_viewing_members_of_an_unknown_group_is_not_found(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_as_admin(client, db_session, email="admin-group-members-unknown@example.com")

    response = await client.get(f"/api/admin/groups/{uuid.uuid4()}/members")

    assert response.status_code == 404


async def test_non_admin_is_forbidden_from_viewing_group_members(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user_with_role(
        db_session, email="learner-group-members@example.com", role_name="Learner"
    )
    group = await _make_group(db_session, name="Forbidden View Group")
    await _login(client, email="learner-group-members@example.com")

    response = await client.get(f"/api/admin/groups/{group.id}/members")

    assert response.status_code == 403


async def test_admin_can_add_a_member_to_a_group(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_as_admin(client, db_session, email="admin-group-add@example.com")
    group = await _make_group(db_session, name="Addable Group")
    target = await _make_user_with_role(
        db_session, email="target-add-group@example.com", role_name="Learner"
    )

    response = await client.post(f"/api/admin/groups/{group.id}/members/{target.id}")

    assert response.status_code == 204
    await db_session.refresh(target, attribute_names=["groups"])
    assert {g.name for g in target.groups} == {"Addable Group"}

    audit_entry = (
        await db_session.execute(select(AuditLog).where(AuditLog.action == "group_member_added"))
    ).scalar_one()
    assert audit_entry.target_user_id == target.id
    assert audit_entry.detail["group_name"] == "Addable Group"


async def test_adding_an_already_member_is_a_conflict(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_as_admin(client, db_session, email="admin-group-add-dup@example.com")
    group = await _make_group(db_session, name="Dup Member Group")
    target = await _make_user_with_role(
        db_session, email="target-add-dup@example.com", role_name="Learner"
    )
    await client.post(f"/api/admin/groups/{group.id}/members/{target.id}")

    response = await client.post(f"/api/admin/groups/{group.id}/members/{target.id}")

    assert response.status_code == 409


async def test_adding_an_erased_user_to_a_group_is_a_conflict(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_as_admin(client, db_session, email="admin-group-add-erased@example.com")
    group = await _make_group(db_session, name="Erased Add Group")
    target = await _make_user_with_role(
        db_session, email="target-add-erased@example.com", role_name="Learner"
    )
    await client.post(f"/api/admin/users/{target.id}/erase")

    response = await client.post(f"/api/admin/groups/{group.id}/members/{target.id}")

    assert response.status_code == 409


async def test_adding_a_member_to_an_unknown_group_is_not_found(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_as_admin(client, db_session, email="admin-group-add-unknown-group@example.com")
    target = await _make_user_with_role(
        db_session, email="target-add-unknown-group@example.com", role_name="Learner"
    )

    response = await client.post(f"/api/admin/groups/{uuid.uuid4()}/members/{target.id}")

    assert response.status_code == 404


async def test_adding_an_unknown_user_to_a_group_is_not_found(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_as_admin(client, db_session, email="admin-group-add-unknown-user@example.com")
    group = await _make_group(db_session, name="Unknown User Group")

    response = await client.post(f"/api/admin/groups/{group.id}/members/{uuid.uuid4()}")

    assert response.status_code == 404


async def test_non_admin_is_forbidden_from_adding_a_group_member(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user_with_role(db_session, email="learner-group-add@example.com", role_name="Learner")
    group = await _make_group(db_session, name="Forbidden Add Group")
    target = await _make_user_with_role(
        db_session, email="target-forbidden-add@example.com", role_name="Learner"
    )
    await _login(client, email="learner-group-add@example.com")

    response = await client.post(f"/api/admin/groups/{group.id}/members/{target.id}")

    assert response.status_code == 403


async def test_admin_can_remove_a_member_from_a_group(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_as_admin(client, db_session, email="admin-group-remove@example.com")
    group = await _make_group(db_session, name="Removable Group")
    target = await _make_user_with_role(
        db_session, email="target-remove-group@example.com", role_name="Learner"
    )
    await client.post(f"/api/admin/groups/{group.id}/members/{target.id}")

    response = await client.delete(f"/api/admin/groups/{group.id}/members/{target.id}")

    assert response.status_code == 204
    await db_session.refresh(target, attribute_names=["groups"])
    assert target.groups == []

    audit_entry = (
        await db_session.execute(select(AuditLog).where(AuditLog.action == "group_member_removed"))
    ).scalar_one()
    assert audit_entry.target_user_id == target.id
    assert audit_entry.detail["group_name"] == "Removable Group"


async def test_removing_a_non_member_is_a_conflict(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_as_admin(client, db_session, email="admin-group-remove-missing@example.com")
    group = await _make_group(db_session, name="No Members Group")
    target = await _make_user_with_role(
        db_session, email="target-remove-missing@example.com", role_name="Learner"
    )

    response = await client.delete(f"/api/admin/groups/{group.id}/members/{target.id}")

    assert response.status_code == 409


async def test_removing_a_member_from_an_unknown_group_is_not_found(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_as_admin(client, db_session, email="admin-group-remove-unknown-group@example.com")
    target = await _make_user_with_role(
        db_session, email="target-remove-unknown-group@example.com", role_name="Learner"
    )

    response = await client.delete(f"/api/admin/groups/{uuid.uuid4()}/members/{target.id}")

    assert response.status_code == 404


async def test_removing_an_unknown_user_from_a_group_is_not_found(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_as_admin(client, db_session, email="admin-group-remove-unknown-user@example.com")
    group = await _make_group(db_session, name="Remove Unknown User Group")

    response = await client.delete(f"/api/admin/groups/{group.id}/members/{uuid.uuid4()}")

    assert response.status_code == 404


async def test_admin_can_remove_an_erased_user_from_a_group(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_as_admin(client, db_session, email="admin-group-remove-erased@example.com")
    group = await _make_group(db_session, name="Erased Remove Group")
    target = await _make_user_with_role(
        db_session, email="target-remove-erased@example.com", role_name="Learner"
    )
    await client.post(f"/api/admin/groups/{group.id}/members/{target.id}")
    await client.post(f"/api/admin/users/{target.id}/erase")

    response = await client.delete(f"/api/admin/groups/{group.id}/members/{target.id}")

    assert response.status_code == 204
    await db_session.refresh(target, attribute_names=["groups"])
    assert target.groups == []


async def test_non_admin_is_forbidden_from_removing_a_group_member(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user_with_role(db_session, email="learner-group-remove@example.com", role_name="Learner")
    group = await _make_group(db_session, name="Forbidden Remove Group")
    target = await _make_user_with_role(
        db_session, email="target-forbidden-remove-group@example.com", role_name="Learner"
    )
    await client.post(f"/api/admin/groups/{group.id}/members/{target.id}")
    await _login(client, email="learner-group-remove@example.com")

    response = await client.delete(f"/api/admin/groups/{group.id}/members/{target.id}")

    assert response.status_code == 403


async def test_group_membership_change_does_not_invalidate_the_targets_other_sessions(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    # Deliberately unlike role assignment (ticket 10): groups are an
    # organizational grouping for targeting future campaigns, not an
    # access-control mechanism, so membership changes don't force a
    # re-login the way a role change does.
    await _login_as_admin(client, db_session, email="admin-group-session@example.com")
    group = await _make_group(db_session, name="Session Survives Group")
    target = await _make_user_with_role(
        db_session, email="target-group-session@example.com", role_name="Learner"
    )

    login_response = await client.post(
        "/api/auth/login",
        json={"email": "target-group-session@example.com", "password": KNOWN_PASSWORD},
    )
    target_token = login_response.cookies[COOKIE_NAME]
    client.cookies.delete(COOKIE_NAME)

    await _login(client, email="admin-group-session@example.com")
    add_response = await client.post(f"/api/admin/groups/{group.id}/members/{target.id}")
    assert add_response.status_code == 204

    client.cookies.set(COOKIE_NAME, target_token)
    still_valid = await client.get("/api/auth/me")
    assert still_valid.status_code == 200


# --- Invite-time group pre-assignment ---


async def test_invite_can_pre_assign_groups_applied_on_acceptance(
    client: AsyncClient, db_session: AsyncSession, sent_emails: list[dict[str, Any]]
) -> None:
    await _login_as_admin(client, db_session, email="admin-invite-group@example.com")
    group = await _make_group(db_session, name="Invite Pre-assigned Group")

    create_response = await client.post(
        "/api/admin/invites",
        json={"email": "invitee-group@example.com", "group_ids": [str(group.id)]},
    )
    assert create_response.status_code == 201
    assert create_response.json()["groups"] == ["Invite Pre-assigned Group"]
    token = _latest_invite_token(sent_emails)

    accept_response = await client.post(
        f"/api/invites/{token}/accept", json={"password": KNOWN_PASSWORD}
    )
    assert accept_response.status_code == 204

    user = (
        await db_session.execute(select(User).where(User.email == "invitee-group@example.com"))
    ).scalar_one()
    group_names = {g.name for g in user.groups}
    assert group_names == {"Invite Pre-assigned Group"}


async def test_invite_with_unknown_group_id_is_unprocessable(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_as_admin(client, db_session, email="admin-invite-unknown-group@example.com")

    response = await client.post(
        "/api/admin/invites",
        json={"email": "invitee-unknown-group@example.com", "group_ids": [str(uuid.uuid4())]},
    )

    assert response.status_code == 422
