import logging
import sys
import re


class SecretRedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        result = super().format(record)
        result = re.sub(r"(api\.telegram\.org/bot)[^/\s]+", r"\1[REDACTED]", result)
        result = re.sub(r"(?i)(Bearer\s+)[^\s\"']+", r"\1[REDACTED]", result)
        from app.core.config import get_settings
        settings = get_settings()
        for secret in (settings.ai_api_key, settings.notion_token, settings.telegram_bot_token, settings.telegram_webhook_secret, settings.publication_recovery_secret):
            if secret:
                result = result.replace(secret, "[REDACTED]")
        return result


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    for handler in logging.getLogger().handlers:
        handler.setFormatter(SecretRedactingFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
