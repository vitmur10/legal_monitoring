"""Source-backed ZIR acceptance test; never publishes to Telegram."""
import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import AsyncSessionLocal
from app.models.source import Source
from app.notion.client import NotionClient
from app.repositories.document_repository import DocumentRepository
from app.services.versioning_service import VersioningService
from app.sources.zir.adapter import ZirAdapter
from app.sources.zir.client import ZirClient


async def main() -> None:
    settings = get_settings()
    missing = [name for name, value in [("NOTION_TOKEN", settings.notion_token), ("NOTION_DATABASE_ID", settings.notion_database_id)] if not value]
    if missing:
        print("BLOCKED: відсутні " + ", ".join(missing))
        return
    client = NotionClient(token=settings.notion_token, database_id=settings.notion_database_id,
                          enabled=True, timeout_seconds=settings.notion_timeout_seconds,
                          property_map=settings.notion_property_map)
    try:
        await client.ensure_database_schema()
    except Exception:
        print("BLOCKED: Notion — потрібні валідні NOTION_TOKEN/NOTION_DATABASE_ID, доступ інтеграції до бази: читання, оновлення схеми, створення сторінок; сумісні типи полів")
        return
    try:
        async with ZirClient() as source_client:
            adapter = ZirAdapter(client=source_client)
            raw = await adapter.fetch_by_id("41820", "ques")
            normalized = await adapter.normalize(raw)
    except Exception:
        print("BLOCKED: не вдалося отримати офіційний текст ЗІР 41820; даних не вигадано")
        return
    try:
        async with AsyncSessionLocal() as session:
            source = (await session.execute(select(Source).where(Source.code == "zir"))).scalar_one_or_none()
            if source is None:
                source = Source(code="zir", name="ЗІР ДПС", base_url="https://zir.tax.gov.ua", enabled=False, check_interval_minutes=60)
                session.add(source)
                await session.flush()
            processing = await VersioningService(enable_stage2_from_env=False).process_document(session, source, normalized, raw.content or "")
            await session.commit()
            version = await DocumentRepository(session).get_version_for_update(processing.current_version_id)
            metadata = dict(version.version_metadata or {})
            stage2 = metadata.get("stage2") or {}
            stage3 = metadata.get("stage3") or {}
            content = (stage3.get("content_versions") or [stage2.get("content") or {}])[-1]
            # No synthetic legal analysis: source text is the fallback smoke article.
            article = content.get("knowledge_base_article") or normalized.content
            analysis = stage2.get("analysis") or {"document_status": "EXPLANATION", "document_type": "Консультація ЗІР", "issuing_authority": "Державна податкова служба України"}
            analysis = {**analysis, "official_source_url": normalized.canonical_url}
            payload = dict(document_id=version.document_id, version_id=version.id,
                           content_version=int(stage3.get("content_version", 1)), title=normalized.title,
                           analysis=analysis, article=article, telegram_message_id=stage3.get("message_id"))
            first = await client.publish(**payload)
            if first.status != "PUBLISHED":
                print("BLOCKED: " + (first.error or first.status))
                return
            metadata["stage4_smoke"] = first.model_dump(mode="json")
            version.version_metadata = metadata
            await session.commit()
            second = await client.publish(**payload)
            print(f"first={first.status} repeat={second.status} same_page={first.page_id == second.page_id} page_url={first.page_url or '-'}")
            if second.status != "PUBLISHED" or second.page_id != first.page_id:
                print("FAILED: повторна публікація не повернула ту саму сторінку")
    except Exception:
        print("BLOCKED: потрібні доступна БД DATABASE_URL і виконані Alembic-міграції")


if __name__ == "__main__":
    configure_logging()
    asyncio.run(main())
