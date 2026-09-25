"""Native export/import: the `.zip` round trip, and every way the archive
half of it can be hostile.

The round trip is the happy path this ticket exists for. Everything else here
is the archive being treated as hostile input: a zip bomb, a path-traversal
entry name, an oversized upload, a page tree carrying a `javascript:` link,
an asset that turns out to be something other than what it claims, and a
manifest that disagrees with the files actually in the archive.
"""

import io
import json
import uuid
import zipfile
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content import SCHEMA_VERSION
from app.core.config import get_settings
from app.models import AuditLog, Module, ModulePage, Role, User
from app.schemas.transfer import EXPORT_FORMAT
from app.security.passwords import hash_password
from app.security.sessions import COOKIE_NAME
from tests.test_upload_sniffing import PNG

KNOWN_PASSWORD = "a-perfectly-fine-passphrase"
SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'


async def _make_user_with_role(db_session: AsyncSession, *, email: str, role_name: str) -> User:
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


def _doc(text_content: str) -> dict[str, Any]:
    return {
        "type": "doc",
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": text_content}]}],
    }


def _image_doc(src: str) -> dict[str, Any]:
    return {
        "type": "doc",
        "content": [{"type": "image", "attrs": {"src": src, "alt": None, "title": None}}],
    }


def _link_doc(href: str) -> dict[str, Any]:
    return {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {
                        "type": "text",
                        "text": "click me",
                        "marks": [{"type": "link", "attrs": {"href": href}}],
                    }
                ],
            }
        ],
    }


async def _make_module(client: AsyncClient, *, title: str = "Phishing Awareness") -> str:
    response = await client.post(
        "/api/content/modules",
        json={"title": title, "description": "How to spot a phish.", "language": "en"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _add_page(
    client: AsyncClient,
    module_id: str,
    *,
    title: str,
    revision: int,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response = await client.post(
        f"/api/content/modules/{module_id}/pages",
        json={
            "draft_revision": revision,
            "title": title,
            "schema_version": SCHEMA_VERSION,
            "body": body if body is not None else _doc(title),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _upload(
    client: AsyncClient,
    module_id: str,
    *,
    data: bytes,
    filename: str,
    kind: str = "image",
) -> Any:
    return await client.post(
        f"/api/content/modules/{module_id}/assets",
        data={"kind": kind},
        files={"file": (filename, data, "application/octet-stream")},
    )


async def _author(client: AsyncClient, db_session: AsyncSession, *, email: str) -> User:
    return await _login_with_role(client, db_session, email=email, role_name="Content Manager")


async def _export(client: AsyncClient, module_id: str) -> bytes:
    response = await client.get(f"/api/content/modules/{module_id}/export")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/zip"
    return response.content


async def _import(client: AsyncClient, data: bytes, *, filename: str = "module.zip") -> Any:
    return await client.post(
        "/api/content/modules/import",
        files={"file": (filename, data, "application/zip")},
    )


def _read_manifest(archive: bytes) -> dict[str, Any]:
    with zipfile.ZipFile(io.BytesIO(archive)) as zf:
        return json.loads(zf.read("module.json").decode("utf-8"))


def _build_zip(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def _minimal_manifest(**overrides: Any) -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "format": EXPORT_FORMAT,
        "title": "Imported Module",
        "description": None,
        "language": "en",
        "estimated_duration_minutes": None,
        "pages": [],
        "assets": [],
    }
    manifest.update(overrides)
    return manifest


# --- The round trip ---------------------------------------------------------


async def test_export_produces_a_zip_with_manifest_and_asset(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _author(client, db_session, email="export-basic@example.com")
    module_id = await _make_module(client)
    await _add_page(client, module_id, title="Intro", revision=1)
    upload = await _upload(client, module_id, data=PNG, filename="diagram.png")
    asset = upload.json()["assets"][0]

    archive = await _export(client, module_id)
    manifest = _read_manifest(archive)

    assert manifest["format"] == EXPORT_FORMAT
    assert manifest["title"] == "Phishing Awareness"
    assert manifest["language"] == "en"
    assert [page["title"] for page in manifest["pages"]] == ["Intro"]
    assert len(manifest["assets"]) == 1
    assert manifest["assets"][0]["id"] == asset["id"]

    with zipfile.ZipFile(io.BytesIO(archive)) as zf:
        stored = zf.read(f"assets/{asset['id']}/diagram.png")
    assert stored == PNG


async def test_import_round_trip_preserves_pages_order_metadata_and_assets(
    client: AsyncClient, db_session: AsyncSession, stored_objects: dict[str, dict[str, Any]]
) -> None:
    await _author(client, db_session, email="round-trip@example.com")
    module_id = await _make_module(client, title="Phishing Awareness 2")
    upload = await _upload(client, module_id, data=PNG, filename="diagram.png")
    asset_url = upload.json()["assets"][0]["url"]
    await _add_page(client, module_id, title="Intro", revision=1)
    await _add_page(
        client, module_id, title="Diagram", revision=2, body=_image_doc(asset_url)
    )
    original = (await client.get(f"/api/content/modules/{module_id}")).json()

    archive = await _export(client, module_id)
    response = await _import(client, archive)
    assert response.status_code == 201, response.text
    imported = response.json()

    assert imported["id"] != module_id
    assert imported["translation_group_id"] != original["translation_group_id"]
    assert imported["title"] == "Phishing Awareness 2"
    assert imported["description"] == "How to spot a phish."
    assert imported["language"] == "en"
    assert imported["status"] == "draft"

    pages_response = await client.get(f"/api/content/modules/{imported['id']}/pages")
    pages = pages_response.json()["pages"]
    assert [page["title"] for page in pages] == ["Intro", "Diagram"]
    assert [page["position"] for page in pages] == [0, 1]

    # The image reference was rewritten to the *new* module's own asset —
    # never left pointing at the original's.
    new_src = pages[1]["body"]["content"][0]["attrs"]["src"]
    assert new_src != asset_url
    assert new_src.startswith(f"/api/modules/{imported['id']}/assets/")

    new_asset_id = new_src.rsplit("/", 1)[-1]
    assets_response = await client.get(f"/api/content/modules/{imported['id']}/assets")
    assets = assets_response.json()["assets"]
    assert len(assets) == 1
    assert assets[0]["id"] == new_asset_id
    assert stored_objects[f"modules/{imported['id']}/assets/{new_asset_id}"]["Body"] == PNG


async def test_import_lands_as_draft_even_when_source_was_published(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _author(client, db_session, email="publish-then-export@example.com")
    module_id = await _make_module(client)
    await _add_page(client, module_id, title="Intro", revision=1)
    publish = await client.post(
        f"/api/content/modules/{module_id}/publish", json={"revision_kind": "minor"}
    )
    assert publish.status_code == 200

    archive = await _export(client, module_id)
    response = await _import(client, archive)
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "draft"
    assert response.json()["current_version_number"] is None


async def test_export_and_import_are_audit_logged(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    author = await _author(client, db_session, email="audit-transfer@example.com")
    module_id = await _make_module(client)
    await _add_page(client, module_id, title="Intro", revision=1)

    archive = await _export(client, module_id)
    exported = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.action == "module_exported",
                AuditLog.detail["module_id"].astext == module_id,
            )
        )
    ).scalar_one()
    assert exported.actor_user_id == author.id
    assert exported.detail["page_count"] == 1

    response = await _import(client, archive)
    imported_id = response.json()["id"]
    imported = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.action == "module_imported",
                AuditLog.detail["module_id"].astext == imported_id,
            )
        )
    ).scalar_one()
    assert imported.actor_user_id == author.id
    assert imported.detail["page_count"] == 1


async def test_administrator_may_also_export_and_import(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login_with_role(
        client, db_session, email="admin-transfer@example.com", role_name="Administrator"
    )
    module_id = await _make_module(client)
    await _add_page(client, module_id, title="Intro", revision=1)

    archive = await _export(client, module_id)
    response = await _import(client, archive)
    assert response.status_code == 201, response.text


# --- Access control ----------------------------------------------------


async def test_a_learner_is_refused_export_and_import(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _author(client, db_session, email="learner-owner@example.com")
    module_id = await _make_module(client)
    await _add_page(client, module_id, title="Intro", revision=1)
    archive = await _export(client, module_id)

    await _login_with_role(
        client, db_session, email="learner-transfer@example.com", role_name="Learner"
    )
    assert (await client.get(f"/api/content/modules/{module_id}/export")).status_code == 403
    assert (await _import(client, archive)).status_code == 403


# --- The archive as hostile input --------------------------------------


async def test_import_rejects_a_non_zip_file(client: AsyncClient, db_session: AsyncSession) -> None:
    await _author(client, db_session, email="not-a-zip@example.com")
    response = await _import(client, b"this is not a zip archive at all")
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "bad_archive"


async def test_import_rejects_an_archive_with_no_module_json(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _author(client, db_session, email="no-manifest@example.com")
    archive = _build_zip({"readme.txt": b"hello"})
    response = await _import(client, archive)
    assert response.status_code == 422


async def test_import_rejects_an_unsupported_format_string(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _author(client, db_session, email="bad-format@example.com")
    manifest = _minimal_manifest(format="traindrain.module/999")
    archive = _build_zip({"module.json": json.dumps(manifest).encode()})
    response = await _import(client, archive)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_module_json"


async def test_import_rejects_a_zip_bomb(client: AsyncClient, db_session: AsyncSession) -> None:
    await _author(client, db_session, email="zip-bomb@example.com")
    manifest = _minimal_manifest()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("module.json", json.dumps(manifest))
        # Five megabytes of zero bytes compress to almost nothing under
        # deflate — a compression ratio no legitimate file reaches.
        archive.writestr("assets/" + str(uuid.uuid4()) + "/bomb.bin", b"\x00" * 5_000_000)

    response = await _import(client, buffer.getvalue())
    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "suspicious_compression_ratio"


async def test_import_rejects_a_path_traversal_entry_name(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _author(client, db_session, email="traversal@example.com")
    archive = _build_zip(
        {
            "module.json": json.dumps(_minimal_manifest()).encode(),
            "../../etc/passwd": b"nope",
        }
    )
    response = await _import(client, archive)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "unexpected_entry"


async def test_import_rejects_an_oversized_archive(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "import_max_archive_bytes", 100, raising=False)

    await _author(client, db_session, email="too-big@example.com")
    archive = _build_zip({"module.json": json.dumps(_minimal_manifest()).encode() + b"x" * 200})
    response = await _import(client, archive)
    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "file_too_large"


async def test_import_rejects_a_page_with_a_javascript_link(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _author(client, db_session, email="js-link@example.com")
    manifest = _minimal_manifest(
        pages=[
            {
                "title": "Dangerous",
                "schema_version": SCHEMA_VERSION,
                "body": _link_doc("javascript:alert(1)"),
            }
        ]
    )
    archive = _build_zip({"module.json": json.dumps(manifest).encode()})

    response = await _import(client, archive)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "bad_href"

    # Rejected outright — never imported with the link stripped.
    modules = (
        await db_session.execute(select(Module).where(Module.title == "Imported Module"))
    ).scalars().all()
    assert modules == []


async def test_import_rejects_a_stale_schema_version(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _author(client, db_session, email="stale-schema@example.com")
    manifest = _minimal_manifest(
        pages=[
            {"title": "Old", "schema_version": SCHEMA_VERSION - 1, "body": _doc("Old")}
        ]
    )
    archive = _build_zip({"module.json": json.dumps(manifest).encode()})
    response = await _import(client, archive)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "schema_version_mismatch"


async def test_import_rejects_too_many_pages(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from app.content import CONSTRAINTS

    max_pages = CONSTRAINTS["limits"]["maxPagesPerModule"]
    await _author(client, db_session, email="too-many-pages@example.com")
    manifest = _minimal_manifest(
        pages=[
            {"title": f"Page {i}", "schema_version": SCHEMA_VERSION, "body": _doc(f"Page {i}")}
            for i in range(max_pages + 1)
        ]
    )
    archive = _build_zip({"module.json": json.dumps(manifest).encode()})
    response = await _import(client, archive)
    assert response.status_code == 409


async def test_import_rejects_a_duplicate_asset_id_in_the_manifest(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _author(client, db_session, email="dupe-asset-id@example.com")
    asset_id = str(uuid.uuid4())
    manifest = _minimal_manifest(
        assets=[
            {
                "id": asset_id,
                "kind": "image",
                "content_type": "image/png",
                "original_filename": "one.png",
                "size_bytes": len(PNG),
            },
            {
                "id": asset_id,
                "kind": "image",
                "content_type": "image/png",
                "original_filename": "one.png",
                "size_bytes": len(PNG),
            },
        ]
    )
    archive = _build_zip(
        {
            "module.json": json.dumps(manifest).encode(),
            f"assets/{asset_id}/one.png": PNG,
        }
    )
    response = await _import(client, archive)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "duplicate_asset_id"


async def test_import_rejects_an_asset_declared_but_missing_from_the_archive(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _author(client, db_session, email="missing-asset-file@example.com")
    manifest = _minimal_manifest(
        assets=[
            {
                "id": str(uuid.uuid4()),
                "kind": "image",
                "content_type": "image/png",
                "original_filename": "ghost.png",
                "size_bytes": len(PNG),
            }
        ]
    )
    archive = _build_zip({"module.json": json.dumps(manifest).encode()})
    response = await _import(client, archive)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "asset_mismatch"


async def test_import_rejects_an_undeclared_asset_entry(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _author(client, db_session, email="undeclared-asset@example.com")
    archive = _build_zip(
        {
            "module.json": json.dumps(_minimal_manifest()).encode(),
            f"assets/{uuid.uuid4()}/uninvited.png": PNG,
        }
    )
    response = await _import(client, archive)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "asset_mismatch"


async def test_import_rejects_an_svg_disguised_as_an_image(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _author(client, db_session, email="disguised-svg@example.com")
    asset_id = str(uuid.uuid4())
    manifest = _minimal_manifest(
        assets=[
            {
                "id": asset_id,
                "kind": "image",
                "content_type": "image/png",
                "original_filename": "logo.png",
                "size_bytes": len(SVG),
            }
        ]
    )
    archive = _build_zip(
        {
            "module.json": json.dumps(manifest).encode(),
            f"assets/{asset_id}/logo.png": SVG,
        }
    )
    response = await _import(client, archive)
    assert response.status_code == 415
    assert response.json()["detail"]["code"] == "svg_not_allowed"


async def test_import_rejects_an_oversized_asset(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "asset_max_image_bytes", len(PNG) - 1, raising=False)

    await _author(client, db_session, email="oversized-asset@example.com")
    asset_id = str(uuid.uuid4())
    manifest = _minimal_manifest(
        assets=[
            {
                "id": asset_id,
                "kind": "image",
                "content_type": "image/png",
                "original_filename": "diagram.png",
                "size_bytes": len(PNG),
            }
        ]
    )
    archive = _build_zip(
        {
            "module.json": json.dumps(manifest).encode(),
            f"assets/{asset_id}/diagram.png": PNG,
        }
    )
    response = await _import(client, archive)
    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "file_too_large"


async def test_import_rejects_when_assets_exceed_the_module_quota(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "asset_max_module_bytes", len(PNG), raising=False)

    await _author(client, db_session, email="over-quota@example.com")
    first_id, second_id = str(uuid.uuid4()), str(uuid.uuid4())
    manifest = _minimal_manifest(
        assets=[
            {
                "id": first_id,
                "kind": "image",
                "content_type": "image/png",
                "original_filename": "one.png",
                "size_bytes": len(PNG),
            },
            {
                "id": second_id,
                "kind": "image",
                "content_type": "image/png",
                "original_filename": "two.png",
                "size_bytes": len(PNG),
            },
        ]
    )
    archive = _build_zip(
        {
            "module.json": json.dumps(manifest).encode(),
            f"assets/{first_id}/one.png": PNG,
            f"assets/{second_id}/two.png": PNG,
        }
    )
    response = await _import(client, archive)
    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "module_quota_exceeded"

    # Nothing was left behind by the rejected import.
    modules = (
        await db_session.execute(select(Module).where(Module.title == "Imported Module"))
    ).scalars().all()
    assert modules == []


async def test_a_failed_import_leaves_no_pages_behind(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Every page is validated before anything is created — including when
    the same manifest also declares a perfectly good asset. A rejection
    leaves no module row, no page row, and nothing else half-built."""
    await _author(client, db_session, email="partial-failure@example.com")
    asset_id = str(uuid.uuid4())
    manifest = _minimal_manifest(
        assets=[
            {
                "id": asset_id,
                "kind": "image",
                "content_type": "image/png",
                "original_filename": "one.png",
                "size_bytes": len(PNG),
            }
        ],
        pages=[
            {
                "title": "Dangerous",
                "schema_version": SCHEMA_VERSION,
                "body": _link_doc("javascript:alert(1)"),
            }
        ],
    )
    archive = _build_zip(
        {
            "module.json": json.dumps(manifest).encode(),
            f"assets/{asset_id}/one.png": PNG,
        }
    )
    response = await _import(client, archive)
    assert response.status_code == 422

    modules = (
        await db_session.execute(select(Module).where(Module.title == "Imported Module"))
    ).scalars().all()
    assert modules == []
    pages = (await db_session.execute(select(ModulePage))).scalars().all()
    assert all(page.module_id not in {module.id for module in modules} for page in pages)
