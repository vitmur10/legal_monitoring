"""Fill missing Notion document dates from dates already stored in PostgreSQL.

Only pages linked to published Knowledge Base records are considered. A date is
written only when the page has an empty Date property; existing dates are kept.
"""
import asyncio

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.db.session import AsyncSessionLocal
from app.models.document_version import DocumentVersion
from app.notion.client import NotionClient


def _published_pages(metadata: dict) -> list[str]:
    stage3 = metadata.get("stage3") or {}
    pages: list[str] = []
    for publication in (stage3.get("knowledge_base_publications") or {}).values():
        if publication.get("status") == "PUBLISHED" and publication.get("page_id"):
            pages.append(str(publication["page_id"]))
    legacy = stage3.get("notion") or {}
    if legacy.get("status") == "PUBLISHED" and legacy.get("page_id"):
        pages.append(str(legacy["page_id"]))
    return list(dict.fromkeys(pages))


async def main() -> None:
    settings = get_settings()
    client = NotionClient(
        token=settings.notion_token,
        database_id=settings.notion_database_id,
        enabled=settings.notion_enabled,
        timeout_seconds=settings.notion_timeout_seconds,
        property_map=settings.notion_property_map,
    )
    if not client.configured:
        raise SystemExit("Notion не налаштовано; жодну сторінку не змінено.")

    updated = 0
    checked = 0
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(DocumentVersion).options(selectinload(DocumentVersion.document))
        )
        versions = result.scalars().all()
        for version in versions:
            metadata = dict(version.version_metadata or {})
            pages = _published_pages(metadata)
            if not pages:
                continue
            analysis = ((metadata.get("stage2") or {}).get("analysis") or {})
            document_date = (
                analysis.get("document_date")
                or metadata.get("document_date")
                or metadata.get("order_date")
            )
            if not document_date:
                continue
            for page_id in pages:
                checked += 1
                if await client.backfill_document_date_if_empty(page_id, str(document_date)):
                    updated += 1
                    print(f"Заповнено дату документа для сторінки {page_id}.")
    print(f"Перевірено сторінок: {checked}; заповнено порожніх дат: {updated}.")


if __name__ == "__main__":
    asyncio.run(main())
