"""Preview or explicitly republish the latest already-published post for QA.

Without --send this is read-only and only prints the exact HTML sent to Telegram.
With --send it posts a duplicate to the configured public channel. It deliberately
does not update the original version's publication status or history.
"""
import argparse
import asyncio
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.db.session import AsyncSessionLocal
from app.models.document_version import DocumentVersion
from app.knowledge_base.labels import label
from app.repositories.document_repository import DocumentRepository
from app.stage3.publisher import MockTelegramPublisher, TelegramBotClient
from app.stage3.review_service import ReviewService


def _was_published(stage3: dict[str, Any]) -> bool:
    if stage3.get("status") != "PUBLISHED":
        return False
    content_version = int(stage3.get("content_version") or 1)
    expected_key = f"v{content_version}:telegram_post"
    return any(
        message.get("key") == expected_key and message.get("message_id")
        for message in stage3.get("publication_messages") or []
    )


async def main(send: bool) -> None:
    settings = get_settings()
    if not (
        settings.telegram_enabled
        and settings.telegram_bot_token
        and settings.telegram_moderation_chat_id
        and settings.telegram_publication_channel_id
    ):
        raise SystemExit("Telegram не налаштовано в .env; дію не виконано.")

    async with AsyncSessionLocal() as session:
        query = (
            select(DocumentVersion)
            .options(selectinload(DocumentVersion.document))
            .order_by(DocumentVersion.detected_at.desc(), DocumentVersion.id.desc())
        )
        versions = list((await session.scalars(query)).all())
        selected = next(
            (
                version
                for version in versions
                if version.document is not None
                and _was_published((version.version_metadata or {}).get("stage3") or {})
            ),
            None,
        )
        if selected is None:
            raise SystemExit("Не знайдено раніше опублікованої статті з підтвердженим Telegram message_id.")

        service = ReviewService(DocumentRepository(session), MockTelegramPublisher())
        item = service._to_review_item(selected)
        if item is None:
            raise SystemExit(f"Не вдалося скласти прев’ю опублікованої версії {selected.id}.")

        analysis = (selected.version_metadata or {}).get("stage2", {}).get("analysis") or {}
        tag_values = analysis.get("topics") or analysis.get("categories") or []
        text = ReviewService.render_channel_post(
            item.telegram_post,
            title=selected.document.title,
            source_url=selected.document.canonical_url,
            tags=ReviewService._hashtags([label(value) for value in tag_values]),
            analysis=analysis,
        )
        print(
            f"Тестова копія останньої вже опублікованої статті: "
            f"document_id={selected.document_id}, version_id={selected.id}, "
            f"original_message_id={((selected.version_metadata or {}).get('stage3') or {}).get('message_id', 'є в історії')}"
        )
        print("\n--- Точний текст Telegram HTML ---\n")
        print(text)
        if not send:
            print("\nЦе лише перегляд; Telegram-повідомлення не надсилалося. Для повторної публікації додайте --send.")
            return

        client = TelegramBotClient(
            token=settings.telegram_bot_token,
            moderation_chat_id=settings.telegram_moderation_chat_id,
            publication_channel_id=settings.telegram_publication_channel_id,
            timeout_seconds=settings.telegram_timeout_seconds,
        )
        result = await client.publish(
            version_id=selected.id,
            text=text,
            dry_run=False,
            parse_mode="HTML",
        )
        print(
            f"Дублікат надіслано в канал {result.target}; "
            f"message_id={result.message_id}, час={result.published_at.isoformat()}. "
            "Запис оригінальної публікації не змінювався."
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--send",
        action="store_true",
        help="надіслати копію останньої вже опублікованої статті в публічний канал",
    )
    args = parser.parse_args()
    asyncio.run(main(args.send))
