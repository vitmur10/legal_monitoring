from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    app_env: str = "development"
    database_url: str = (
        "postgresql+asyncpg://legal_monitoring:legal_monitoring@localhost:5432/legal_monitoring"
    )
    log_level: str = "INFO"
    scheduler_enabled: bool = False
    ai_enabled: bool = True
    ai_api_key: str | None = None
    ai_model_relevance: str = "gpt-4o-mini"
    ai_model_analysis: str = "gpt-4o"
    ai_model_content: str | None = None
    ai_base_url: str = "https://api.openai.com/v1"
    ai_timeout_seconds: float = 60.0
    ai_max_retries: int = 2
    ai_relevance_max_input_chars: int = 24000
    ai_analysis_max_input_chars: int = 36000
    ai_relevance_max_output_tokens: int | None = 800
    ai_analysis_max_output_tokens: int | None = 2200
    ai_content_max_output_tokens: int | None = 2600
    ai_max_total_tokens_per_document: int | None = None
    telegram_enabled: bool = False
    telegram_bot_token: str | None = None
    telegram_moderation_chat_id: str | None = None
    telegram_publication_channel_id: str | None = None
    telegram_allowed_user_ids: str = ""
    telegram_webhook_secret: str | None = None
    telegram_timeout_seconds: float = 30.0
    publication_recovery_secret: str | None = None
    notion_enabled: bool = False
    notion_token: str | None = None
    notion_database_id: str | None = None
    notion_timeout_seconds: float = 30.0
    notion_property_map: str = ""

    @property
    def telegram_allowed_users(self) -> set[int]:
        return {
            int(value.strip())
            for value in self.telegram_allowed_user_ids.split(",")
            if value.strip()
        }

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
