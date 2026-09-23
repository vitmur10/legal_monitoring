import asyncio
import logging
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import get_settings
from app.db.session import AsyncSessionLocal
from app.stage3.factory import create_review_service
from app.stage3.publisher import TelegramBotClient
from app.stage3.telegram_service import TelegramWorkflowService


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger("telegram-bot")


async def main() -> None:
    settings = get_settings()
    missing = []
    if not settings.telegram_enabled:
        missing.insert(0, "TELEGRAM_ENABLED=true")
    if not settings.telegram_bot_token:
        missing.append("TELEGRAM_BOT_TOKEN")
    if missing:
        raise RuntimeError(
            "Telegram is disabled or settings are missing: " + ", ".join(missing)
        )

    telegram = TelegramBotClient(
        token=settings.telegram_bot_token,
        moderation_chat_id=settings.telegram_moderation_chat_id or "0",
        publication_channel_id=settings.telegram_publication_channel_id or "0",
        timeout_seconds=settings.telegram_timeout_seconds,
    )
    await telegram.delete_webhook()

    logger.info("Telegram bot polling started")
    if not _workflow_configured(settings):
        logger.info(
            "Discovery mode: send /chatid in the group and /myid to get Telegram IDs"
        )
    offset = None
    while True:
        try:
            updates = await telegram.get_updates(offset=offset)
            for update in updates:
                offset = int(update["update_id"]) + 1
                if await _handle_id_command(telegram, update):
                    continue
                if not _workflow_configured(settings):
                    logger.warning(
                        "Stage 3 settings are incomplete; only /chatid and /myid are available"
                    )
                    continue
                async with AsyncSessionLocal() as session:
                    service = create_review_service(session, settings)
                    result = await TelegramWorkflowService(service).handle_update(update)
                    await session.commit()
                    logger.info(
                        "update_id=%s handled=%s action=%s version_id=%s status=%s",
                        update["update_id"],
                        result.handled,
                        result.action,
                        result.version_id,
                        result.status,
                    )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Telegram polling iteration failed")
            await asyncio.sleep(2)


def _workflow_configured(settings) -> bool:
    return bool(
        settings.telegram_moderation_chat_id
        and settings.telegram_publication_channel_id
        and settings.telegram_allowed_user_ids
    )


async def _handle_id_command(telegram: TelegramBotClient, update: dict) -> bool:
    message = update.get("message") or {}
    text = str(message.get("text") or "").split("@", 1)[0].strip().lower()
    if text not in {"/chatid", "/myid"}:
        return False
    chat = message.get("chat") or {}
    user = message.get("from") or {}
    if text == "/chatid":
        response = f"ID цього чату: {chat.get('id')}"
    else:
        response = f"Ваш Telegram ID: {user.get('id')}"
    await telegram.send_text(chat_id=chat["id"], text=response)
    return True


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
