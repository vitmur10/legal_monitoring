import asyncio
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.models.document import Document
from app.models.document_version import DocumentVersion
from app.stage3.publisher import MockTelegramPublisher
from app.stage3.review_service import ReviewService
from app.stage3.schemas import PublishRequest, ReviewDecisionRequest


class InMemoryRepository:
    def __init__(self, versions: list[DocumentVersion]) -> None:
        self.versions = versions

    async def list_versions_with_documents(self) -> list[DocumentVersion]:
        return self.versions

    async def get_version(self, version_id: int) -> DocumentVersion | None:
        return next((version for version in self.versions if version.id == version_id), None)


def build_demo_version() -> DocumentVersion:
    document = Document(
        id=1,
        source_id=1,
        identity_key="crs-demo",
        identity_type="external_id",
        external_id="1025759",
        canonical_url="https://tax.gov.ua/media-tsentr/novini/1025759.html",
        title="CRS 2.0",
        document_type="news",
        first_seen_at=datetime.now(timezone.utc),
        last_seen_at=datetime.now(timezone.utc),
    )
    version = DocumentVersion(
        id=101,
        document_id=1,
        version_number=1,
        raw_content="raw",
        normalized_content="CRS 2.0 діє з 01.07.2026.",
        content_hash="demo",
        detected_at=datetime.now(timezone.utc),
        version_metadata={
            "stage2": {
                "status": "ANALYZED",
                "analysis": {
                    "importance": "HIGH",
                    "categories": ["CRS", "INTERNATIONAL_TAX"],
                    "summary": "Оновлено правила CRS 2.0 для фінансових рахунків.",
                },
                "content": {
                    "telegram_post": (
                        "CRS 2.0: з 01.07.2026 діють оновлені правила звітності "
                        "щодо фінансових рахунків. Джерело: tax.gov.ua"
                    ),
                    "knowledge_base_article": (
                        "CRS 2.0: розгорнута стаття для Бази знань. Описано статус, "
                        "дату набрання чинності, кого стосується зміна, практичний "
                        "вплив, дії, ризики та офіційне джерело."
                    ),
                },
            }
        },
    )
    version.document = document
    return version


async def main() -> None:
    service = ReviewService(InMemoryRepository([build_demo_version()]), MockTelegramPublisher())

    print("=" * 50)
    print("STAGE 3 REVIEW QUEUE DEMO")
    print("=" * 50)

    items = await service.list_items()
    item = items[0]
    print("\nPENDING REVIEW ITEM")
    print(f"version_id: {item.version_id}")
    print(f"status: {item.status}")
    print(f"title: {item.title}")
    print(f"importance: {item.importance}")
    print(f"telegram_post: {item.telegram_post}")

    approved = await service.approve(
        item.version_id,
        ReviewDecisionRequest(reviewer="demo", note="approved for dry-run publish"),
    )
    print("\nAPPROVAL")
    print(f"status: {approved.status}")
    print(f"reviewer: {approved.reviewer}")

    published = await service.publish(item.version_id, PublishRequest(target="telegram", dry_run=True))
    print("\nMOCK TELEGRAM PUBLISH")
    print(f"status: {published.status}")
    print(f"target: {published.target}")
    print(f"message_id: {published.message_id}")
    print(f"published_at: {published.published_at}")


if __name__ == "__main__":
    asyncio.run(main())
