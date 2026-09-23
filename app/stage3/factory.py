from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.content_service import AIContentService
from app.ai.provider import OpenAICompatibleProvider
from app.core.config import Settings, get_settings
from app.repositories.document_repository import DocumentRepository
from app.stage3.publisher import MockTelegramPublisher, TelegramBotClient
from app.stage3.review_service import ReviewService
from app.notion.client import NotionClient
from app.knowledge_base.service import KnowledgeBaseService


def create_review_service(
    session: AsyncSession, settings: Settings | None = None
) -> ReviewService:
    settings = settings or get_settings()
    notion = NotionClient(token=settings.notion_token, database_id=settings.notion_database_id,
                          enabled=settings.notion_enabled, timeout_seconds=settings.notion_timeout_seconds,
                          property_map=settings.notion_property_map)
    if not (
        settings.telegram_enabled
        and settings.telegram_bot_token
        and settings.telegram_moderation_chat_id
        and settings.telegram_publication_channel_id
    ):
        return ReviewService(DocumentRepository(session), MockTelegramPublisher(), knowledge_base_service=KnowledgeBaseService(notion))

    telegram = TelegramBotClient(
        token=settings.telegram_bot_token,
        moderation_chat_id=settings.telegram_moderation_chat_id,
        publication_channel_id=settings.telegram_publication_channel_id,
        timeout_seconds=settings.telegram_timeout_seconds,
    )
    content_service = None
    if settings.ai_enabled and settings.ai_api_key:
        provider = OpenAICompatibleProvider(
            api_key=settings.ai_api_key,
            base_url=settings.ai_base_url,
            timeout_seconds=settings.ai_timeout_seconds,
            max_retries=settings.ai_max_retries,
        )
        content_service = AIContentService(
            provider,
            settings.ai_model_content or settings.ai_model_analysis,
            max_output_tokens=settings.ai_content_max_output_tokens,
        )
    return ReviewService(
        DocumentRepository(session),
        telegram,
        moderation_client=telegram,
        content_service=content_service,
        allowed_user_ids=settings.telegram_allowed_users,
        knowledge_base_service=KnowledgeBaseService(notion),
    )
