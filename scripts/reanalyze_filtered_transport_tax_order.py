"""Re-run Stage 2 for one known false-negative Minfin transport-tax form order.

This script never publishes to the public Telegram channel or to Notion. If Stage 2
marks the item relevant, it sends the existing moderation card to the configured
moderation chat. It is safe to rerun after a dispatch failure: ANALYZED items with
no moderation card are dispatched without another AI request.
"""
import asyncio
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.ai.stage2_service import create_stage2_service_from_settings
from app.core.config import get_settings
from app.db.session import AsyncSessionLocal
from app.models.document import Document
from app.models.document_version import DocumentVersion
from app.models.enums import ProcessingStatus
from app.models.source import Source
from app.stage3.factory import create_review_service


TITLE_MARKER = "Податкової декларації з транспортного податку"


def _has_moderation_card(metadata: dict) -> bool:
    stage3 = metadata.get("stage3") or {}
    content_version = int(stage3.get("content_version") or 1)
    messages: Sequence[dict] = stage3.get("moderation_messages") or []
    return any(int(message.get("content_version") or 0) == content_version for message in messages)


async def main() -> None:
    settings = get_settings()
    if not settings.ai_enabled or not settings.ai_api_key:
        raise SystemExit("AI не налаштовано; повторний аналіз не запускався.")
    if not (
        settings.telegram_enabled
        and settings.telegram_bot_token
        and settings.telegram_moderation_chat_id
        and settings.telegram_publication_channel_id
    ):
        raise SystemExit("Telegram-модерацію не налаштовано; повторний аналіз не запускався.")

    stage2 = create_stage2_service_from_settings(settings)
    if stage2 is None:
        raise SystemExit("Не вдалося створити Stage 2; повторний аналіз не запускався.")

    async with AsyncSessionLocal() as session:
        query = (
            select(Document, DocumentVersion)
            .join(Source, Source.id == Document.source_id)
            .join(DocumentVersion, DocumentVersion.id == Document.current_version_id)
            .where(
                Source.code == "minfin",
                Document.title.ilike(f"%{TITLE_MARKER}%"),
            )
            .options(selectinload(DocumentVersion.document))
            .with_for_update(of=DocumentVersion)
        )
        matches = list((await session.execute(query)).all())
        if len(matches) != 1:
            raise SystemExit(
                f"Очікувався рівно один поточний документ Мінфіну з назвою про форму декларації "
                f"(знайдено {len(matches)}); нічого не змінено."
            )

        document, version = matches[0]
        metadata = dict(version.version_metadata or {})
        stage2_metadata = dict(metadata.get("stage2") or {})
        current_status = stage2_metadata.get("status")

        if _has_moderation_card(metadata):
            print(f"Для версії {version.id} moderation card вже надіслано; повторної дії немає.")
            return

        if current_status in {"FILTERED_OUT", "AI_FAILED"}:
            relevance = stage2_metadata.get("relevance") or {}
            expected_relevance = current_status == "AI_FAILED"
            if relevance.get("relevant") is not expected_relevance:
                raise SystemExit(
                    f"Статус {current_status} має неочікуваний результат relevance; "
                    "нічого не змінено."
                )
            result = await stage2.process(
                status=ProcessingStatus.NEW,
                document=document,
                current_version=version,
                previous_version=None,
                source_code="minfin",
            )
            if result is None:
                raise SystemExit("Stage 2 не повернув результат; нічого не збережено.")
            metadata["stage2"] = result
            version.version_metadata = metadata
            await session.commit()
            print(f"Повторний Stage 2 завершено: document_id={document.id}, version_id={version.id}, "
                  f"status={result.get('status')}, relevance_prompt="
                  f"{(result.get('prompt_versions') or {}).get('relevance')}.")
            if result.get("status") != "ANALYZED":
                return
        elif current_status != "ANALYZED":
            raise SystemExit(
                f"Поточний Stage 2 status={current_status!r}; очікувався FILTERED_OUT/AI_FAILED або "
                "ANALYZED без moderation card. Нічого не змінено."
            )

        review_service = create_review_service(session, settings)
        dispatched = await review_service.dispatch_to_moderation(version.id)
        if dispatched is None:
            raise SystemExit("Не вдалося надіслати moderation card.")
        await session.commit()
        print(
            f"Moderation card надіслано: document_id={document.id}, version_id={version.id}, "
            f"status={dispatched.status.value}. Публічний канал і Notion не змінювалися."
        )


if __name__ == "__main__":
    asyncio.run(main())
