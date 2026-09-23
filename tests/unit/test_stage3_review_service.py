from datetime import datetime, timezone

from app.models.document import Document
from app.models.document_version import DocumentVersion
from app.stage3.publisher import MockTelegramPublisher
from app.stage3.review_service import ReviewService
from app.stage3.schemas import PublicationStatus, PublishRequest, ReviewDecisionRequest


class FakeRepository:
    def __init__(self, versions: list[DocumentVersion]) -> None:
        self.versions = versions

    async def list_versions_with_documents(self) -> list[DocumentVersion]:
        return self.versions

    async def get_version(self, version_id: int) -> DocumentVersion | None:
        return next((version for version in self.versions if version.id == version_id), None)


def review_version(stage3: dict | None = None) -> DocumentVersion:
    document = Document(
        id=10,
        source_id=1,
        identity_key="crs",
        identity_type="external_id",
        external_id="1025759",
        canonical_url="https://tax.gov.ua/media-tsentr/novini/1025759.html",
        title="CRS 2.0",
        document_type="news",
        first_seen_at=datetime.now(timezone.utc),
        last_seen_at=datetime.now(timezone.utc),
    )
    version = DocumentVersion(
        id=20,
        document_id=10,
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
            },
            "stage3": stage3 or {},
        },
    )
    version.document = document
    return version


async def test_review_queue_lists_analyzed_items_as_ready_by_default() -> None:
    service = ReviewService(FakeRepository([review_version()]), MockTelegramPublisher())

    items = await service.list_items()

    assert len(items) == 1
    assert items[0].status == PublicationStatus.READY_FOR_REVIEW
    assert items[0].telegram_post
    assert items[0].knowledge_base_article


async def test_approve_and_reject_update_stage3_metadata() -> None:
    version = review_version()
    service = ReviewService(FakeRepository([version]), MockTelegramPublisher())

    approved = await service.approve(20, ReviewDecisionRequest(reviewer="owner", note="ok"))
    rejected = await service.reject(20, ReviewDecisionRequest(reviewer="owner", note="revise"))

    assert approved is not None
    assert approved.status == PublicationStatus.APPROVED
    assert rejected is not None
    assert rejected.status == PublicationStatus.REJECTED
    assert version.version_metadata["stage3"]["status"] == "REJECTED"
    assert version.version_metadata["stage3"]["note"] == "revise"


async def test_publish_requires_approval() -> None:
    service = ReviewService(FakeRepository([review_version()]), MockTelegramPublisher())

    result = await service.publish(20, PublishRequest(dry_run=True))

    assert result is not None
    assert result.status == PublicationStatus.FAILED
    assert "APPROVED" in (result.error or "")


async def test_approved_item_can_be_mock_published_once() -> None:
    version = review_version(stage3={"status": "APPROVED"})
    service = ReviewService(FakeRepository([version]), MockTelegramPublisher())

    first = await service.publish(20, PublishRequest(dry_run=True))
    second = await service.publish(20, PublishRequest(dry_run=True))

    assert first is not None
    assert first.status == PublicationStatus.APPROVED
    assert first.message_id
    assert second is not None
    assert second.status == PublicationStatus.APPROVED
    assert second.message_id == first.message_id


def test_full_article_is_rendered_as_clean_telegram_text() -> None:
    rendered = ReviewService.render_full_article(
        "## Суть події\n\n**CRS 2.0** змінено.\n\n"
        "## Джерело\n\n[Офіційний сайт](https://example.test)"
    )

    assert rendered.startswith("<b>Повна стаття</b>")
    assert "<b>Суть події</b>" in rendered
    assert "**" not in rendered
    assert "##" not in rendered
    assert '<a href="https://example.test">Офіційний сайт</a>' in rendered
