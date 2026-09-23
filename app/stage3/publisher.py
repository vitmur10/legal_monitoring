from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

import httpx
from pydantic import BaseModel

from app.core.http import system_ssl_context
from app.knowledge_base.errors import PublicationRejected


class PublishResult(BaseModel):
    target: str
    message_id: str
    published_at: datetime


class TelegramPublisher(ABC):
    @abstractmethod
    async def publish(
        self,
        *,
        version_id: int,
        text: str,
        dry_run: bool = True,
        parse_mode: str | None = None,
    ) -> PublishResult:
        raise NotImplementedError


class ModerationMessageResult(BaseModel):
    chat_id: str
    message_id: str
    sent_at: datetime


class TelegramBotClient(TelegramPublisher):
    def __init__(
        self,
        *,
        token: str,
        moderation_chat_id: str,
        publication_channel_id: str,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.moderation_chat_id = moderation_chat_id
        self.publication_channel_id = publication_channel_id
        self.timeout_seconds = timeout_seconds

    async def publish(
        self,
        *,
        version_id: int,
        text: str,
        dry_run: bool = True,
        parse_mode: str | None = None,
    ) -> PublishResult:
        if dry_run:
            return await MockTelegramPublisher().publish(
                version_id=version_id,
                text=text,
                dry_run=True,
                parse_mode=parse_mode,
            )
        payload: dict[str, Any] = {
            "chat_id": self.publication_channel_id,
            "text": text,
            "disable_web_page_preview": True,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
        message = await self._request(
            "sendMessage",
            payload,
        )
        return PublishResult(
            target=self.publication_channel_id,
            message_id=str(message["message_id"]),
            published_at=datetime.now(timezone.utc),
        )

    async def send_moderation_card(
        self, *, version_id: int, content_version: int, text: str
    ) -> ModerationMessageResult:
        message = await self._request(
            "sendMessage",
            {
                "chat_id": self.moderation_chat_id,
                "text": text,
                "disable_web_page_preview": True,
                "reply_markup": self._review_markup(version_id, content_version),
            },
        )
        return ModerationMessageResult(
            chat_id=str(message["chat"]["id"]),
            message_id=str(message["message_id"]),
            sent_at=datetime.now(timezone.utc),
        )

    async def send_text(
        self,
        *,
        chat_id: str | int,
        text: str,
        force_reply: bool = False,
        review_version_id: int | None = None,
        content_version: int | None = None,
        parse_mode: str | None = None,
    ) -> str:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if force_reply:
            payload["reply_markup"] = {
                "force_reply": True,
                "selective": True,
                "input_field_placeholder": "Напишіть коментар для виправлення",
            }
        elif review_version_id is not None and content_version is not None:
            payload["reply_markup"] = self._review_markup(review_version_id, content_version)
        message = await self._request("sendMessage", payload)
        return str(message["message_id"])

    @staticmethod
    def _review_markup(version_id: int, content_version: int) -> dict[str, Any]:
        return {
            "inline_keyboard": [
                [
                    {"text": "📢 Telegram", "callback_data": f"s3:a:{version_id}:{content_version}"},
                    {"text": "📚 Telegram + База", "callback_data": f"s3:b:{version_id}:{content_version}"},
                ],
                [
                    {"text": "✏️ Виправити", "callback_data": f"s3:e:{version_id}:{content_version}"},
                    {"text": "❌ Відхилити", "callback_data": f"s3:r:{version_id}:{content_version}"},
                ],
                [
                    {"text": "📚 Додати в Базу", "callback_data": f"s3:k:{version_id}:{content_version}"},
                ],
                [
                    {
                        "text": "Повна стаття",
                        "callback_data": f"s3:v:{version_id}:{content_version}",
                    }
                ],
            ]
        }

    async def answer_callback(self, callback_query_id: str, text: str) -> None:
        await self._request(
            "answerCallbackQuery", {"callback_query_id": callback_query_id, "text": text}
        )

    async def get_updates(self, *, offset: int | None = None, timeout: int = 25) -> list[dict]:
        payload: dict[str, Any] = {
            "timeout": timeout,
            "allowed_updates": ["message", "callback_query"],
        }
        if offset is not None:
            payload["offset"] = offset
        return await self._request("getUpdates", payload)

    async def delete_webhook(self) -> None:
        await self._request("deleteWebhook", {"drop_pending_updates": False})

    async def _request(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(
            timeout=self.timeout_seconds,
            verify=system_ssl_context(),
        ) as client:
            response = await client.post(f"{self.base_url}/{method}", json=payload)
        if response.is_error:
            if 400 <= response.status_code < 500 and response.status_code != 408:
                raise PublicationRejected(f"Telegram відхилив запит: HTTP {response.status_code}")
            raise RuntimeError(f"Помилка Telegram API: HTTP {response.status_code}")
        body = response.json()
        if not body.get("ok"):
            if 400 <= int(body.get("error_code") or 0) < 500 and body.get("error_code") != 408:
                raise PublicationRejected("Telegram відхилив запит")
            raise RuntimeError("Невідомий результат Telegram API")
        return body["result"]


class MockTelegramPublisher(TelegramPublisher):
    async def publish(
        self,
        *,
        version_id: int,
        text: str,
        dry_run: bool = True,
        parse_mode: str | None = None,
    ) -> PublishResult:
        if not text.strip():
            raise PublicationRejected("telegram_post is empty")
        timestamp = datetime.now(timezone.utc)
        prefix = "dry-run" if dry_run else "mock"
        return PublishResult(
            target="telegram",
            message_id=f"{prefix}-{version_id}-{int(timestamp.timestamp())}",
            published_at=timestamp,
        )
