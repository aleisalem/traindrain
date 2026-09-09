"""Module assets end to end: upload, quota, delivery, and who is refused.

The interesting half of this file is the denied direction. An upload path is
where hostile bytes arrive, and an asset URL is where an IDOR shows up, so both
are tested from the outside by somebody who should not get in.
"""

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content.uploads import IMAGE_EXTENSIONS
from app.models import AuditLog, ModuleAsset, Role, User
from app.security.passwords import hash_password
from app.security.sessions import COOKIE_NAME
from tests.conftest import FakeS3Client
from tests.test_upload_sniffing import GIF, JPEG, PDF, PNG, WEBP, ooxml

KNOWN_PASSWORD = "a-perfectly-fine-passphrase"

DOCX = ooxml(
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
)
SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'


async def _make_user_with_role(
    db_session: AsyncSession, *, email: str, role_name: str
) -> User:
    role = (await db_session.execute(select(Role).where(Role.name == role_name))).scalar_one()
    user = User(
        id=uuid.uuid4(),
        email=email,
        password_hash=hash_password(KNOWN_PASSWORD),
        first_name="Cora",
        last_name="Manager",
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


async def _login_with_role(
    client: AsyncClient, db_session: AsyncSession, *, email: str, role_name: str
) -> User:
    user = await _make_user_with_role(db_session, email=email, role_name=role_name)
    await _login(client, email=email)
    return user


async def _create_module(client: AsyncClient) -> str:
    response = await client.post(
        "/api/content/modules",
        json={"title": "Phishing Awareness", "language": "en"},
    )
    assert response.status_code == 201
    return response.json()["id"]


async def _upload(
    client: AsyncClient,
    module_id: str,
    *,
    data: bytes,
    filename: str,
    kind: str = "image",
    content_type: str = "application/octet-stream",
) -> Any:
    return await client.post(
        f"/api/content/modules/{module_id}/assets",
        data={"kind": kind},
        files={"file": (filename, data, content_type)},
    )


async def _author_with_module(
    client: AsyncClient, db_session: AsyncSession, *, email: str
) -> str:
    await _login_with_role(client, db_session, email=email, role_name="Content Manager")
    return await _create_module(client)


# --- The happy path -------------------------------------------------------


async def test_an_author_uploads_an_image(
    client: AsyncClient, db_session: AsyncSession, stored_objects: dict[str, dict[str, Any]]
) -> None:
    module_id = await _author_with_module(client, db_session, email="asset-image@example.com")

    response = await _upload(client, module_id, data=PNG, filename="diagram.png")

    assert response.status_code == 201
    body = response.json()
    assert len(body["assets"]) == 1
    asset = body["assets"][0]
    assert asset["kind"] == "image"
    assert asset["content_type"] == "image/png"
    assert asset["size_bytes"] == len(PNG)
    assert asset["original_filename"] == "diagram.png"
    assert asset["uploaded_by"]["display_name"] == "Cora Manager"
    assert asset["referenced_by_pages"] == 0
    assert body["total_bytes"] == len(PNG)

    # Keys are namespaced by module and built from opaque UUIDs.
    key = f"modules/{module_id}/assets/{asset['id']}"
    assert key in stored_objects
    assert stored_objects[key]["ContentType"] == "image/png"
    assert stored_objects[key]["ServerSideEncryption"] == "AES256"
    # An image renders in place, so no download disposition.
    assert "ContentDisposition" not in stored_objects[key]


async def test_the_asset_url_matches_the_schemas_image_src_pattern(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """An `image` node pointing at this URL has to be a document the server accepts."""
    import re

    from app.content import CONSTRAINTS

    module_id = await _author_with_module(client, db_session, email="asset-pattern@example.com")
    response = await _upload(client, module_id, data=PNG, filename="diagram.png")

    url = response.json()["assets"][0]["url"]
    assert re.fullmatch(CONSTRAINTS["imageSrcPattern"], url)


async def test_an_uploaded_image_can_be_embedded_in_a_page(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """The end-to-end point of the ticket: the src passes ticket 2's allowlist."""
    module_id = await _author_with_module(client, db_session, email="asset-embed@example.com")
    upload = await _upload(client, module_id, data=PNG, filename="diagram.png")
    url = upload.json()["assets"][0]["url"]

    pages = await client.get(f"/api/content/modules/{module_id}/pages")
    created = await client.post(
        f"/api/content/modules/{module_id}/pages",
        json={
            "draft_revision": pages.json()["draft_revision"],
            "title": "How a phish looks",
            "schema_version": pages.json()["schema_version"],
            "body": {
                "type": "doc",
                "content": [{"type": "image", "attrs": {"src": url, "alt": "A phish"}}],
            },
        },
    )

    assert created.status_code == 201
    assert created.json()["pages"][0]["body"]["content"][0]["attrs"]["src"] == url

    # And the module's asset list now reports it as in use, so deleting it is
    # a decision the author makes knowingly.
    listed = await client.get(f"/api/content/modules/{module_id}/assets")
    assert listed.json()["assets"][0]["referenced_by_pages"] == 1


async def test_an_image_hosted_elsewhere_is_still_refused(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Assets existing does not widen what an `image` node may point at."""
    module_id = await _author_with_module(client, db_session, email="asset-remote@example.com")
    pages = await client.get(f"/api/content/modules/{module_id}/pages")

    response = await client.post(
        f"/api/content/modules/{module_id}/pages",
        json={
            "draft_revision": pages.json()["draft_revision"],
            "title": "Page",
            "schema_version": pages.json()["schema_version"],
            "body": {
                "type": "doc",
                "content": [
                    {"type": "image", "attrs": {"src": "https://evil.example/track.png"}}
                ],
            },
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "bad_src"


async def test_an_author_uploads_an_attachment_served_as_a_download(
    client: AsyncClient, db_session: AsyncSession, stored_objects: dict[str, dict[str, Any]]
) -> None:
    module_id = await _author_with_module(client, db_session, email="asset-attach@example.com")

    response = await _upload(
        client, module_id, data=PDF, filename="policy.pdf", kind="attachment"
    )

    assert response.status_code == 201
    asset = response.json()["assets"][0]
    assert asset["kind"] == "attachment"
    assert asset["content_type"] == "application/pdf"

    stored = stored_objects[f"modules/{module_id}/assets/{asset['id']}"]
    # Non-sniffable and a download, both stated on the object itself rather
    # than only on the URL that happens to fetch it. S3 cannot emit an
    # `X-Content-Type-Options` header on an object, so "non-sniffable" is the
    # type itself: an octet-stream marked as an attachment is downloaded by
    # every browser, never rendered. The true type stays on the row, which is
    # what the response above reports and the authoring UI shows.
    assert stored["ContentType"] == "application/octet-stream"
    assert stored["ContentDisposition"].startswith('attachment; filename="policy.pdf"')


async def test_a_download_filename_with_non_ascii_is_encoded_not_interpolated(
    client: AsyncClient, db_session: AsyncSession, stored_objects: dict[str, dict[str, Any]]
) -> None:
    module_id = await _author_with_module(client, db_session, email="asset-utf8@example.com")

    response = await _upload(
        client, module_id, data=PDF, filename="Sicherheitsrichtlinie-Übersicht.pdf",
        kind="attachment",
    )

    asset = response.json()["assets"][0]
    disposition = stored_objects[f"modules/{module_id}/assets/{asset['id']}"][
        "ContentDisposition"
    ]
    assert "filename*=UTF-8''" in disposition
    assert "%C3%9C" in disposition
    # Nothing raw and non-ASCII goes into the header value.
    disposition.encode("ascii")


@pytest.mark.parametrize(
    ("data", "filename", "kind", "expected_type"),
    [
        (JPEG, "photo.jpg", "image", "image/jpeg"),
        (GIF, "anim.gif", "image", "image/gif"),
        (WEBP, "shot.webp", "image", "image/webp"),
        (
            DOCX,
            "handbook.docx",
            "attachment",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
        (b"a,b\n1,2\n", "roster.csv", "attachment", "text/plain; charset=utf-8"),
    ],
)
async def test_every_allowed_type_round_trips(
    client: AsyncClient,
    db_session: AsyncSession,
    data: bytes,
    filename: str,
    kind: str,
    expected_type: str,
) -> None:
    module_id = await _author_with_module(
        client, db_session, email=f"asset-ok-{filename}@example.com"
    )

    response = await _upload(client, module_id, data=data, filename=filename, kind=kind)

    assert response.status_code == 201
    assert response.json()["assets"][0]["content_type"] == expected_type


# --- Hostile uploads ------------------------------------------------------


async def test_an_svg_upload_is_rejected(
    client: AsyncClient, db_session: AsyncSession, stored_objects: dict[str, dict[str, Any]]
) -> None:
    module_id = await _author_with_module(client, db_session, email="asset-svg@example.com")

    response = await _upload(
        client, module_id, data=SVG, filename="logo.svg", content_type="image/svg+xml"
    )

    assert response.status_code == 415
    assert response.json()["detail"]["code"] == "svg_not_allowed"
    # Rejected means nothing was persisted, in either place.
    assert stored_objects == {}
    assert (
        await db_session.execute(select(ModuleAsset).where(ModuleAsset.module_id == module_id))
    ).first() is None


async def test_an_svg_renamed_to_png_is_rejected(
    client: AsyncClient, db_session: AsyncSession, stored_objects: dict[str, dict[str, Any]]
) -> None:
    """The client's declared content type is not what is being checked."""
    module_id = await _author_with_module(client, db_session, email="asset-svgpng@example.com")

    response = await _upload(
        client, module_id, data=SVG, filename="logo.png", content_type="image/png"
    )

    assert response.status_code == 415
    assert response.json()["detail"]["code"] == "svg_not_allowed"
    assert stored_objects == {}


async def test_a_file_whose_bytes_contradict_its_declared_kind_is_rejected(
    client: AsyncClient, db_session: AsyncSession, stored_objects: dict[str, dict[str, Any]]
) -> None:
    module_id = await _author_with_module(client, db_session, email="asset-mismatch@example.com")

    response = await _upload(
        client, module_id, data=PDF, filename="policy.png", kind="image",
        content_type="image/png",
    )

    assert response.status_code == 415
    assert response.json()["detail"]["code"] == "unrecognised_image"
    assert stored_objects == {}


async def test_an_executable_declared_as_an_attachment_is_rejected(
    client: AsyncClient, db_session: AsyncSession, stored_objects: dict[str, dict[str, Any]]
) -> None:
    module_id = await _author_with_module(client, db_session, email="asset-exe@example.com")

    response = await _upload(
        client,
        module_id,
        data=b"MZ\x90\x00\x03" + b"\x00" * 64,
        filename="reader.pdf",
        kind="attachment",
    )

    assert response.status_code == 415
    assert stored_objects == {}


async def test_an_unknown_kind_is_rejected_at_the_edge(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    module_id = await _author_with_module(client, db_session, email="asset-kind@example.com")

    response = await _upload(client, module_id, data=PNG, filename="clip.png", kind="video")

    assert response.status_code == 422


# --- Size caps ------------------------------------------------------------


async def test_an_oversized_file_is_rejected_before_anything_is_persisted(
    client: AsyncClient,
    db_session: AsyncSession,
    stored_objects: dict[str, dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "asset_max_image_bytes", 1024, raising=False)
    module_id = await _author_with_module(client, db_session, email="asset-big@example.com")

    response = await _upload(client, module_id, data=PNG + b"\x00" * 4096, filename="big.png")

    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "file_too_large"
    assert stored_objects == {}


async def test_an_over_quota_module_is_rejected(
    client: AsyncClient,
    db_session: AsyncSession,
    stored_objects: dict[str, dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import get_settings

    settings = get_settings()
    module_id = await _author_with_module(client, db_session, email="asset-quota@example.com")

    first = await _upload(client, module_id, data=PNG, filename="one.png")
    assert first.status_code == 201

    # The module's budget is now smaller than what it already holds plus one
    # more byte, so the next upload cannot fit however small it is.
    monkeypatch.setattr(settings, "asset_max_module_bytes", len(PNG), raising=False)
    second = await _upload(client, module_id, data=JPEG, filename="two.jpg")

    assert second.status_code == 413
    assert second.json()["detail"]["code"] == "module_quota_exceeded"
    # The first upload is untouched; only the second was refused.
    assert len(stored_objects) == 1


# --- Delivery -------------------------------------------------------------


async def test_an_asset_request_redirects_to_a_short_lived_presigned_url(
    client: AsyncClient, db_session: AsyncSession, s3_client: FakeS3Client
) -> None:
    module_id = await _author_with_module(client, db_session, email="asset-serve@example.com")
    upload = await _upload(client, module_id, data=PNG, filename="diagram.png")
    url = upload.json()["assets"][0]["url"]

    response = await client.get(url, follow_redirects=False)

    assert response.status_code == 307
    location = response.headers["location"]
    # A different origin from the application's, so a content-type escape has
    # no same-origin document to act against.
    assert location.startswith("https://assets.example.test/")
    assert "X-Amz-Signature" in location
    # Five minutes, and the cached redirect always outlives by less than that.
    assert s3_client.signed[-1][1] == 300
    assert response.headers["cache-control"] == "private, max-age=60"


async def test_the_presigned_url_ttl_comes_from_configuration(
    client: AsyncClient,
    db_session: AsyncSession,
    s3_client: FakeS3Client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The signature expires — the URL is not a durable capability."""
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "asset_url_ttl_seconds", 60, raising=False)
    module_id = await _author_with_module(client, db_session, email="asset-ttl@example.com")
    upload = await _upload(client, module_id, data=PNG, filename="diagram.png")

    await client.get(upload.json()["assets"][0]["url"], follow_redirects=False)

    assert s3_client.signed[-1][1] == 60


async def test_an_asset_id_from_another_module_is_a_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """The URL's module has to be the asset's module — not just any real pair."""
    await _login_with_role(
        client, db_session, email="asset-idor@example.com", role_name="Content Manager"
    )
    mine = await _create_module(client)
    theirs = await _create_module(client)
    upload = await _upload(client, mine, data=PNG, filename="diagram.png")
    asset_id = upload.json()["assets"][0]["id"]

    response = await client.get(
        f"/api/modules/{theirs}/assets/{asset_id}", follow_redirects=False
    )

    assert response.status_code == 404


async def test_a_learner_gets_404_on_an_asset(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """No learner access model exists yet, so implicit deny is the whole answer."""
    module_id = await _author_with_module(client, db_session, email="asset-owner@example.com")
    upload = await _upload(client, module_id, data=PNG, filename="diagram.png")
    url = upload.json()["assets"][0]["url"]

    await client.post("/api/auth/logout")
    client.cookies.clear()
    await _login_with_role(
        client, db_session, email="asset-learner@example.com", role_name="Learner"
    )

    response = await client.get(url, follow_redirects=False)

    assert response.status_code == 404


async def test_an_asset_request_without_a_session_is_401(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """There is no anonymous path to an asset, signed URL or not."""
    module_id = await _author_with_module(client, db_session, email="asset-anon@example.com")
    upload = await _upload(client, module_id, data=PNG, filename="diagram.png")
    url = upload.json()["assets"][0]["url"]

    client.cookies.clear()
    response = await client.get(url, follow_redirects=False)

    assert response.status_code == 401


# --- Authoring authorization ---------------------------------------------


@pytest.mark.parametrize("method", ["GET", "POST", "DELETE"])
async def test_a_learner_is_refused_every_authoring_asset_route(
    client: AsyncClient, db_session: AsyncSession, method: str
) -> None:
    module_id = await _author_with_module(client, db_session, email=f"asset-cm-{method}@example.com")
    await client.post("/api/auth/logout")
    client.cookies.clear()
    await _login_with_role(
        client, db_session, email=f"asset-l-{method}@example.com", role_name="Learner"
    )

    path = f"/api/content/modules/{module_id}/assets"
    if method == "GET":
        response = await client.get(path)
    elif method == "POST":
        response = await _upload(client, module_id, data=PNG, filename="diagram.png")
    else:
        response = await client.delete(f"{path}/{uuid.uuid4()}")

    assert response.status_code == 403


async def test_an_administrator_may_upload_too(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_with_role(
        client, db_session, email="asset-admin@example.com", role_name="Administrator"
    )
    module_id = await _create_module(client)

    response = await _upload(client, module_id, data=PNG, filename="diagram.png")

    assert response.status_code == 201


async def test_an_upload_to_an_unknown_module_is_a_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_with_role(
        client, db_session, email="asset-nomodule@example.com", role_name="Content Manager"
    )

    response = await _upload(client, str(uuid.uuid4()), data=PNG, filename="diagram.png")

    assert response.status_code == 404


# --- Deletion -------------------------------------------------------------


async def test_deleting_an_asset_deletes_the_underlying_object(
    client: AsyncClient, db_session: AsyncSession, stored_objects: dict[str, dict[str, Any]]
) -> None:
    module_id = await _author_with_module(client, db_session, email="asset-del@example.com")
    upload = await _upload(client, module_id, data=PNG, filename="diagram.png")
    asset_id = upload.json()["assets"][0]["id"]
    assert stored_objects != {}

    response = await client.delete(f"/api/content/modules/{module_id}/assets/{asset_id}")

    assert response.status_code == 200
    assert response.json()["assets"] == []
    assert response.json()["total_bytes"] == 0
    assert stored_objects == {}


async def test_deleting_an_asset_of_another_module_is_a_404(
    client: AsyncClient, db_session: AsyncSession, stored_objects: dict[str, dict[str, Any]]
) -> None:
    await _login_with_role(
        client, db_session, email="asset-delidor@example.com", role_name="Content Manager"
    )
    mine = await _create_module(client)
    theirs = await _create_module(client)
    upload = await _upload(client, mine, data=PNG, filename="diagram.png")
    asset_id = upload.json()["assets"][0]["id"]

    response = await client.delete(f"/api/content/modules/{theirs}/assets/{asset_id}")

    assert response.status_code == 404
    # And the object it named is still there.
    assert stored_objects != {}


async def test_deleting_an_asset_does_not_disturb_the_others(
    client: AsyncClient, db_session: AsyncSession, stored_objects: dict[str, dict[str, Any]]
) -> None:
    module_id = await _author_with_module(client, db_session, email="asset-multi@example.com")
    first = await _upload(client, module_id, data=PNG, filename="one.png")
    await _upload(client, module_id, data=JPEG, filename="two.jpg")

    response = await client.delete(
        f"/api/content/modules/{module_id}/assets/{first.json()['assets'][0]['id']}"
    )

    assert [asset["original_filename"] for asset in response.json()["assets"]] == ["two.jpg"]
    assert len(stored_objects) == 1


# --- Audit ----------------------------------------------------------------


async def test_upload_and_delete_are_audit_logged(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    author = await _login_with_role(
        client, db_session, email="asset-audit@example.com", role_name="Content Manager"
    )
    module_id = await _create_module(client)
    upload = await _upload(client, module_id, data=PDF, filename="policy.pdf", kind="attachment")
    asset_id = upload.json()["assets"][0]["id"]
    await client.delete(f"/api/content/modules/{module_id}/assets/{asset_id}")

    entries = list(
        (
            await db_session.execute(
                select(AuditLog)
                .where(AuditLog.actor_user_id == author.id)
                .order_by(AuditLog.timestamp)
            )
        ).scalars()
    )
    actions = [entry.action for entry in entries]
    assert "module_asset_uploaded" in actions
    assert "module_asset_deleted" in actions

    uploaded = next(entry for entry in entries if entry.action == "module_asset_uploaded")
    assert uploaded.detail["asset_id"] == asset_id
    assert uploaded.detail["content_type"] == "application/pdf"
    assert uploaded.detail["size_bytes"] == len(PDF)


# --- The allowlist itself -------------------------------------------------


def test_svg_is_absent_from_the_image_allowlist() -> None:
    """A regression guard on the allowlist rather than only on the code path."""
    assert not any("svg" in extensions for extensions in IMAGE_EXTENSIONS.values())
    assert "image/svg+xml" not in IMAGE_EXTENSIONS


# --- The bucket the objects land in --------------------------------------


async def test_the_local_bucket_is_created_private_and_encrypted(
    s3_client: FakeS3Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The local environment must not be more permissive than the deployed one.

    Terraform owns these settings in a real deployment. Asserting them here is
    what keeps the two from drifting — and it is the only place they *can* be
    asserted, since LocalStack Community does not enforce S3 request
    authorization at all, so an unsigned GET succeeding locally proves nothing.
    """
    from app.core.config import get_settings
    from app.storage import ensure_assets_bucket

    settings = get_settings()
    monkeypatch.setattr(settings, "aws_endpoint_url", "http://localstack:4566", raising=False)

    await ensure_assets_bucket(s3_client)

    assert s3_client.created_buckets == [settings.assets_bucket]
    assert s3_client.public_access_blocks[settings.assets_bucket] == {
        "BlockPublicAcls": True,
        "IgnorePublicAcls": True,
        "BlockPublicPolicy": True,
        "RestrictPublicBuckets": True,
    }
    assert s3_client.encryption[settings.assets_bucket]["Rules"][0][
        "ApplyServerSideEncryptionByDefault"
    ] == {"SSEAlgorithm": "AES256"}


async def test_the_bucket_is_not_created_without_an_endpoint_override(
    s3_client: FakeS3Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """In a real deployment the task role has no permission to create a bucket."""
    from app.core.config import get_settings
    from app.storage import ensure_assets_bucket

    monkeypatch.setattr(get_settings(), "aws_endpoint_url", None, raising=False)

    await ensure_assets_bucket(s3_client)

    assert s3_client.created_buckets == []
