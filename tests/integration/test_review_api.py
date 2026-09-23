from datetime import datetime, timezone

from httpx import ASGITransport, AsyncClient

from app.db.session import get_session
from app.main import app
from app.models.document import Document
from app.models.document_version import DocumentVersion
from tests.fixtures.builders import source


async def seed_review_item(session) -> int:
    src = source()
    session.add(src)
    await session.flush()
    document = Document(
        source_id=src.id,
        identity_key="crs",
        identity_type="external_id",
        external_id="1025759",
        canonical_url="https://tax.gov.ua/media-tsentr/novini/1025759.html",
        title="CRS 2.0",
        document_type="news",
        first_seen_at=datetime.now(timezone.utc),
        last_seen_at=datetime.now(timezone.utc),
    )
    session.add(document)
    await session.flush()
    version = DocumentVersion(
        document_id=document.id,
        version_number=1,
        raw_content="raw",
        normalized_content="content",
        content_hash="hash",
        detected_at=datetime.now(timezone.utc),
        version_metadata={
            "stage2": {
                "status": "ANALYZED",
                "analysis": {
                    "importance": "HIGH",
                    "categories": ["CRS"],
                    "summary": "Оновлено правила CRS 2.0.",
                },
                "content": {
                    "telegram_post": "Короткий Telegram-пост про CRS 2.0.",
                    "knowledge_base_article": "Розгорнута стаття для Бази знань про CRS 2.0.",
                },
            }
        },
    )
    session.add(version)
    await session.flush()
    document.current_version_id = version.id
    await session.commit()
    return version.id


async def client_for(session):
    async def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_review_api_lists_approves_and_mock_publishes(session) -> None:
    version_id = await seed_review_item(session)
    async with await client_for(session) as client:
        listed = await client.get("/review/items")
        approved = await client.post(
            f"/review/items/{version_id}/approve",
            json={"reviewer": "owner", "note": "approved for smoke"},
        )
        published = await client.post(
            f"/review/items/{version_id}/publish",
            json={"target": "telegram", "dry_run": True},
        )

    app.dependency_overrides.clear()

    assert listed.status_code == 200
    assert listed.json()[0]["status"] == "READY_FOR_REVIEW"
    assert approved.status_code == 200
    assert approved.json()["status"] == "APPROVED"
    assert published.status_code == 200
    assert published.json()["status"] == "APPROVED"
    assert published.json()["message_id"].startswith("dry-run-")


async def test_stage2_result_endpoint_returns_metadata(session) -> None:
    version_id = await seed_review_item(session)
    document_id = (await session.get(DocumentVersion, version_id)).document_id
    async with await client_for(session) as client:
        response = await client.get(f"/documents/{document_id}/versions/{version_id}/stage2")

    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["status"] == "ANALYZED"
