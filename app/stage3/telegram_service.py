from typing import Any

from app.stage3.review_service import ReviewService
from app.stage3.schemas import (
    PublicationStatus,
    ReviewDecisionRequest,
    RevisionRequest,
    TelegramUpdateResult,
)


class TelegramWorkflowService:
    def __init__(self, review_service: ReviewService) -> None:
        self.review_service = review_service

    async def handle_update(self, update: dict[str, Any]) -> TelegramUpdateResult:
        callback = update.get("callback_query")
        if callback:
            return await self._handle_callback(callback)
        message = update.get("message")
        if message and message.get("text"):
            return await self._handle_message(message)
        return TelegramUpdateResult(handled=False, detail="Unsupported Telegram update")

    async def _handle_callback(self, callback: dict[str, Any]) -> TelegramUpdateResult:
        user = callback.get("from") or {}
        user_id = int(user.get("id") or 0)
        callback_id = str(callback.get("id") or "")
        if not self.review_service.is_allowed(user_id):
            await self._answer(callback_id, "У вас немає права погоджувати матеріали")
            return TelegramUpdateResult(handled=True, action="FORBIDDEN", detail="User is not allowed")

        parsed = self._parse_callback(str(callback.get("data") or ""))
        if parsed is None:
            await self._answer(callback_id, "Невідома дія")
            return TelegramUpdateResult(handled=False, detail="Invalid callback data")
        action, version_id, content_version = parsed
        version = await self.review_service._get_version_for_update(version_id)
        if version is None:
            await self._answer(callback_id, "Матеріал не знайдено")
            return TelegramUpdateResult(handled=True, action=action, version_id=version_id)
        current = int(((version.version_metadata or {}).get("stage3") or {}).get("content_version", 1))
        if content_version != current:
            await self._answer(callback_id, "Це застаріла версія матеріалу")
            return TelegramUpdateResult(
                handled=True, action="STALE", version_id=version_id, detail="Stale content version"
            )
        if action == "VIEW_ARTICLE":
            chat_id = str(((callback.get("message") or {}).get("chat") or {}).get("id") or "")
            content = self.review_service._current_content(version)
            raw_parts = self._split_message(content.knowledge_base_article, limit=3500)
            article_parts = [
                self.review_service.render_full_article(part, include_header=index == 0)
                for index, part in enumerate(raw_parts)
            ]
            article_parts[0] = (
                f"<b>Версія для погодження: Draft v{current}</b>\n\n{article_parts[0]}"
            )
            if self.review_service.moderation_client is not None:
                for index, part in enumerate(article_parts):
                    is_last = index == len(article_parts) - 1
                    await self.review_service.moderation_client.send_text(
                        chat_id=chat_id,
                        text=part,
                        review_version_id=version_id if is_last else None,
                        content_version=current if is_last else None,
                        parse_mode="HTML",
                    )
            text = "Повну статтю надіслано"
            await self._answer(callback_id, text)
            return TelegramUpdateResult(
                handled=True,
                action=action,
                version_id=version_id,
                status=self.review_service._status(version),
                detail=text,
            )
        terminal_status = self.review_service._status(version)
        if terminal_status == PublicationStatus.RECONCILIATION_REQUIRED:
            text = "Результат публікації невідомий. Потрібна звірка; повторне відправлення заблоковано"
            await self._answer(callback_id, text)
            return TelegramUpdateResult(handled=True, action="RECONCILIATION_REQUIRED", version_id=version_id, status=terminal_status, detail=text)
        if action in {"ADD_KNOWLEDGE_BASE", "APPROVE_WITH_KNOWLEDGE_BASE"} and terminal_status == PublicationStatus.PUBLISHED:
            result = await self.review_service.publish_to_knowledge_base(version_id)
            text = "Додано в Базу знань" if result and result.status == "PUBLISHED" else "База знань недоступна; повторіть спробу"
            if result and result.status == "UNKNOWN":
                text = "Результат Бази невідомий; потрібна звірка. Повторне створення заблоковано"
            await self._answer(callback_id, text)
            return TelegramUpdateResult(handled=True, action=action, version_id=version_id, status=terminal_status, detail=text)
        if terminal_status in {PublicationStatus.PUBLISHED, PublicationStatus.REJECTED}:
            text = (
                "Матеріал уже опубліковано"
                if terminal_status == PublicationStatus.PUBLISHED
                else "Матеріал уже відхилено"
            )
            await self._answer(callback_id, text)
            return TelegramUpdateResult(
                handled=True,
                action="ALREADY_DECIDED",
                version_id=version_id,
                status=terminal_status,
                detail=text,
            )

        reviewer = self._display_name(user)
        decision = ReviewDecisionRequest(reviewer=reviewer, reviewer_id=user_id)
        if action == "ADD_KNOWLEDGE_BASE":
            await self._answer(callback_id, "Спочатку опублікуйте погоджений матеріал у Telegram")
            return TelegramUpdateResult(handled=True, action=action, version_id=version_id, status=terminal_status)
        if action in {"APPROVE", "APPROVE_WITH_KNOWLEDGE_BASE"}:
            result = await self.review_service.approve_and_publish(version_id, decision, include_knowledge_base=action == "APPROVE_WITH_KNOWLEDGE_BASE")
            status = result.status if result else None
            text = "Матеріал опубліковано" if status == PublicationStatus.PUBLISHED else "Помилка публікації"
            if status == PublicationStatus.RECONCILIATION_REQUIRED:
                text = "Результат Telegram невідомий; потрібна звірка. Повторне відправлення заблоковано"
            if result and result.knowledge_base_status and result.knowledge_base_status != "PUBLISHED":
                text = "Telegram опубліковано; База недоступна. Натисніть «Додати в Базу» для повтору"
                if result.knowledge_base_status == "UNKNOWN":
                    text = "Telegram опубліковано; результат Бази невідомий. Потрібна звірка"
        elif action == "REJECT":
            result = await self.review_service.reject(version_id, decision)
            status = result.status if result else None
            text = "Матеріал відхилено"
        else:
            chat_id = str(((callback.get("message") or {}).get("chat") or {}).get("id") or "")
            result = await self.review_service.request_revision(
                version_id,
                reviewer=reviewer,
                reviewer_id=user_id,
                chat_id=chat_id,
            )
            status = result.status if result else None
            text = (
                "Відповідайте на це повідомлення або надішліть команду:\n"
                "/fix ваш коментар для виправлення"
            )
            if self.review_service.moderation_client is not None:
                await self.review_service.moderation_client.send_text(
                    chat_id=chat_id,
                    text=text,
                    force_reply=True,
                )
        await self._answer(callback_id, text)
        return TelegramUpdateResult(
            handled=True,
            action=action,
            version_id=version_id,
            status=status,
            detail=text,
        )

    async def _handle_message(self, message: dict[str, Any]) -> TelegramUpdateResult:
        user = message.get("from") or {}
        user_id = int(user.get("id") or 0)
        chat_id = str((message.get("chat") or {}).get("id") or "")
        if not self.review_service.is_allowed(user_id):
            return TelegramUpdateResult(handled=False, action="FORBIDDEN")
        version_id = await self.review_service.find_pending_revision(user_id, chat_id)
        if version_id is None:
            return TelegramUpdateResult(handled=False, detail="No pending revision")
        comment = str(message["text"]).strip()
        command, separator, command_comment = comment.partition(" ")
        if command.split("@", 1)[0].lower() == "/fix":
            if not separator or not command_comment.strip():
                if self.review_service.moderation_client is not None:
                    await self.review_service.moderation_client.send_text(
                        chat_id=chat_id,
                        text="Формат команди: /fix ваш коментар для виправлення",
                    )
                return TelegramUpdateResult(
                    handled=True,
                    action="REVISE_COMMENT_REQUIRED",
                    version_id=version_id,
                    status=PublicationStatus.REVISION_REQUESTED,
                )
            comment = command_comment.strip()
        result = await self.review_service.revise(
            version_id,
            RevisionRequest(
                reviewer=self._display_name(user),
                reviewer_id=user_id,
                comment=comment,
            ),
        )
        return TelegramUpdateResult(
            handled=True,
            action="REVISE",
            version_id=version_id,
            status=result.status if result else None,
            detail="New content version sent for review",
        )

    async def _answer(self, callback_id: str, text: str) -> None:
        if callback_id and self.review_service.moderation_client is not None:
            await self.review_service.moderation_client.answer_callback(callback_id, text)

    def _parse_callback(self, value: str) -> tuple[str, int, int] | None:
        parts = value.split(":")
        if len(parts) != 4 or parts[0] != "s3" or parts[1] not in {"a", "b", "k", "e", "r", "v"}:
            return None
        try:
            version_id, content_version = int(parts[2]), int(parts[3])
        except ValueError:
            return None
        action = {
            "a": "APPROVE",
            "b": "APPROVE_WITH_KNOWLEDGE_BASE",
            "k": "ADD_KNOWLEDGE_BASE",
            "e": "REVISE",
            "r": "REJECT",
            "v": "VIEW_ARTICLE",
        }[parts[1]]
        return action, version_id, content_version

    @staticmethod
    def _split_message(text: str, limit: int = 4000) -> list[str]:
        if len(text) <= limit:
            return [text]
        parts: list[str] = []
        remaining = text
        while remaining:
            if len(remaining) <= limit:
                parts.append(remaining)
                break
            split_at = remaining.rfind("\n\n", 0, limit)
            if split_at < limit // 2:
                split_at = remaining.rfind("\n", 0, limit)
            if split_at < limit // 2:
                split_at = remaining.rfind(" ", 0, limit)
            if split_at < limit // 2:
                split_at = limit
            parts.append(remaining[:split_at].rstrip())
            remaining = remaining[split_at:].lstrip()
        return parts

    def _display_name(self, user: dict[str, Any]) -> str:
        return (
            user.get("username")
            or " ".join(filter(None, [user.get("first_name"), user.get("last_name")]))
            or str(user.get("id"))
        )
