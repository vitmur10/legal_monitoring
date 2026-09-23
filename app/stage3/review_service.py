from datetime import datetime, timezone
import html
import re
from typing import Any
from uuid import uuid4
from hashlib import sha256
from urllib.parse import urlparse

from app.ai.content_service import AIContentService
from app.ai.schemas import ContentGenerationResult, FullAnalysisResult, Stage2Input
from app.models.document_version import DocumentVersion
from app.repositories.document_repository import DocumentRepository
from app.stage3.publisher import TelegramBotClient, TelegramPublisher
from app.stage3.schemas import (
    ModerationDispatchResult,
    PublicationStatus,
    PublicationRecoveryRequest,
    PublishActionResult,
    PublishRequest,
    ReviewDecisionRequest,
    ReviewDecisionResult,
    ReviewItemRead,
    RevisionRequest,
)
from app.knowledge_base.service import KnowledgeBaseService, KnowledgeBasePublicationResult
from app.knowledge_base.labels import label
from app.knowledge_base.errors import PublicationRejected


class ReviewService:
    def __init__(
        self,
        repository: DocumentRepository,
        publisher: TelegramPublisher,
        *,
        moderation_client: TelegramBotClient | None = None,
        content_service: AIContentService | None = None,
        allowed_user_ids: set[int] | None = None,
        knowledge_base_service: KnowledgeBaseService | None = None,
    ) -> None:
        self.repository = repository
        self.publisher = publisher
        self.moderation_client = moderation_client
        self.content_service = content_service
        self.allowed_user_ids = allowed_user_ids or set()
        self.knowledge_base_service = knowledge_base_service

    async def list_items(
        self, status: PublicationStatus | None = PublicationStatus.READY_FOR_REVIEW
    ) -> list[ReviewItemRead]:
        versions = await self.repository.list_versions_with_documents()
        items = [self._to_review_item(version) for version in versions]
        filtered = [item for item in items if item is not None]
        return filtered if status is None else [item for item in filtered if item.status == status]

    async def get_stage2_result(self, version_id: int) -> dict[str, Any] | None:
        version = await self.repository.get_version(version_id)
        return None if version is None else (version.version_metadata or {}).get("stage2")

    async def dispatch_to_moderation(
        self, version_id: int, *, force: bool = False
    ) -> ModerationDispatchResult | None:
        if self.moderation_client is None:
            raise RuntimeError("Telegram moderation is not configured")
        version = await self._get_version_for_update(version_id)
        if version is None:
            return None
        item = self._to_review_item(version)
        if item is None:
            raise ValueError("Document version has no generated Stage 2 content")
        metadata, stage3 = self._ensure_stage3(version)
        content_version = int(stage3["content_version"])
        messages = list(stage3.get("moderation_messages") or [])
        existing = next(
            (entry for entry in messages if entry.get("content_version") == content_version), None
        )
        if existing and not force:
            return ModerationDispatchResult(
                version_id=version_id,
                status=self._status(version),
                chat_id=str(existing["chat_id"]),
                message_id=str(existing["message_id"]),
                sent_at=existing["sent_at"],
            )
        result = await self.moderation_client.send_moderation_card(
            version_id=version_id,
            content_version=content_version,
            text=self._render_moderation_card(item, content_version),
        )
        messages.append(
            {
                "content_version": content_version,
                "chat_id": result.chat_id,
                "message_id": result.message_id,
                "sent_at": result.sent_at.isoformat(),
            }
        )
        stage3["moderation_messages"] = messages
        stage3["status"] = PublicationStatus.READY_FOR_REVIEW.value
        self._append_history(stage3, "SENT_FOR_REVIEW", content_version=content_version)
        self._save_stage3(version, metadata, stage3)
        return ModerationDispatchResult(
            version_id=version_id,
            status=PublicationStatus.READY_FOR_REVIEW,
            chat_id=result.chat_id,
            message_id=result.message_id,
            sent_at=result.sent_at,
        )

    async def approve(
        self, version_id: int, payload: ReviewDecisionRequest
    ) -> ReviewDecisionResult | None:
        return await self._set_decision(version_id, PublicationStatus.APPROVED, payload)

    async def approve_and_publish(
        self, version_id: int, payload: ReviewDecisionRequest, *, include_knowledge_base: bool = False
    ) -> PublishActionResult | None:
        version = await self._get_version_for_update(version_id)
        if version is None:
            return None
        self._assert_publishable(version)
        if self._has_pending_attempt(version, "telegram"):
            return PublishActionResult(version_id=version.id, status=PublicationStatus.RECONCILIATION_REQUIRED,
                                      target="telegram", error="Результат попередньої спроби невідомий; потрібна звірка")
        if self._status(version) == PublicationStatus.PUBLISHED:
            result = self._published_result(version, "telegram")
            if include_knowledge_base:
                kb = await self.publish_to_knowledge_base(version_id)
                result.knowledge_base_status = kb.status if kb else None
            return result
        if self._status(version) != PublicationStatus.APPROVED:
            await self._set_decision_on_version(version, PublicationStatus.APPROVED, payload)
        return await self._publish_version(version, PublishRequest(target="telegram", dry_run=False, include_knowledge_base=include_knowledge_base))

    async def publish_to_knowledge_base(self, version_id: int) -> KnowledgeBasePublicationResult | None:
        version = await self._get_version_for_update(version_id)
        if version is None:
            return None
        self._assert_publishable(version)
        if self._status(version) != PublicationStatus.PUBLISHED:
            raise ValueError("До Бази можна додати лише опубліковану погоджену редакцію")
        metadata, stage3 = self._ensure_stage3(version)
        key = str(stage3["content_version"])
        publications = dict(stage3.get("knowledge_base_publications") or {})
        legacy = stage3.get("notion") or {}
        if legacy.get("content_version") == int(key):
            publications.setdefault(key, legacy)
        existing = publications.get(key) or {}
        if existing.get("status") == "PUBLISHED":
            return KnowledgeBasePublicationResult.model_validate(existing)
        if self._has_pending_attempt(version, "knowledge_base"):
            return KnowledgeBasePublicationResult(status="UNKNOWN", error="Потрібна звірка попередньої спроби Бази")
        if self.knowledge_base_service is None:
            return KnowledgeBasePublicationResult(status="NOT_CONFIGURED", error="Базу знань не налаштовано")
        previous = next((p for k, p in reversed(list(publications.items())) if k != key and p.get("page_id")), {})
        if not previous:
            versions = await self.repository.list_versions_with_documents()
            for candidate in sorted(versions, key=lambda v: (v.version_number, v.id), reverse=True):
                if candidate.document_id == version.document_id and candidate.version_number < version.version_number:
                    prior = (candidate.version_metadata or {}).get("stage3") or {}
                    entries = list((prior.get("knowledge_base_publications") or {}).values()) + [prior.get("notion") or {}]
                    previous = next((p for p in reversed(entries) if p.get("page_id")), {})
                    if previous:
                        break
        content = self._current_content(version)
        analysis = dict((metadata.get("stage2") or {}).get("analysis") or {})
        analysis["official_source_url"] = version.document.canonical_url
        analysis["source_published_at"] = (
            version.document.published_at.date().isoformat()
            if version.document.published_at
            else None
        )
        # Minfin order rows carry the signed date in source metadata. The AI can
        # leave document_date empty, but Notion's Date property should still be
        # populated from this authoritative source field.
        source_metadata = metadata
        analysis["document_date"] = (
            analysis.get("document_date")
            or source_metadata.get("document_date")
            or source_metadata.get("order_date")
        )
        analysis.setdefault("document_type", version.document.document_type)
        attempt_id = await self._start_attempt(version, "knowledge_base", content.knowledge_base_article)
        result = await self.knowledge_base_service.publish_to_knowledge_base(
            document_id=version.document_id, version_id=version.id,
            content_version=int(stage3["content_version"]), title=version.document.title,
            analysis=analysis,
            article=content.knowledge_base_article,
            telegram_message_id=stage3.get("message_id"),
            previous_page_id=previous.get("page_id"),
        )
        version, metadata, stage3 = await self._resume_attempt(version.id, "knowledge_base", int(key), attempt_id)
        publications = dict(stage3.get("knowledge_base_publications") or {})
        publications[key] = {"status": result.status, "page_id": result.page_id, "page_url": result.page_url,
                             "published_at": result.published_at.isoformat() if result.published_at else None,
                             "document_id": version.document_id, "version_id": version.id,
                             "content_version": int(stage3["content_version"]), "error": result.error,
                             "previous_page_id": previous.get("page_id")}
        stage3["knowledge_base_publications"] = publications
        self._record_attempt_result(stage3, "knowledge_base", int(key), result.status)
        self._append_history(stage3, "KNOWLEDGE_BASE_PUBLICATION", content_version=int(key), status=result.status)
        self._save_stage3(version, metadata, stage3)
        await self._checkpoint()
        return result

    async def reject(
        self, version_id: int, payload: ReviewDecisionRequest
    ) -> ReviewDecisionResult | None:
        return await self._set_decision(version_id, PublicationStatus.REJECTED, payload)

    async def request_revision(
        self,
        version_id: int,
        *,
        reviewer: str | None,
        reviewer_id: int,
        chat_id: str,
    ) -> ReviewDecisionResult | None:
        version = await self._get_version_for_update(version_id)
        if version is None:
            return None
        self._assert_no_pending_attempt(version)
        now = datetime.now(timezone.utc)
        metadata, stage3 = self._ensure_stage3(version)
        stage3.update(
            {
                "status": PublicationStatus.REVISION_REQUESTED.value,
                "pending_revision": {
                    "reviewer": reviewer,
                    "reviewer_id": reviewer_id,
                    "chat_id": str(chat_id),
                    "content_version": stage3["content_version"],
                    "requested_at": now.isoformat(),
                },
            }
        )
        self._append_history(
            stage3,
            "REVISION_REQUESTED",
            actor=reviewer,
            actor_id=reviewer_id,
            content_version=stage3["content_version"],
        )
        self._save_stage3(version, metadata, stage3)
        return ReviewDecisionResult(
            version_id=version_id,
            status=PublicationStatus.REVISION_REQUESTED,
            decided_at=now,
            reviewer=reviewer,
        )

    async def find_pending_revision(self, reviewer_id: int, chat_id: str) -> int | None:
        versions = await self.repository.list_versions_with_documents()
        for version in versions:
            stage3 = (version.version_metadata or {}).get("stage3") or {}
            pending = stage3.get("pending_revision") or {}
            if (
                self._status(version) == PublicationStatus.REVISION_REQUESTED
                and pending.get("reviewer_id") == reviewer_id
                and str(pending.get("chat_id")) == str(chat_id)
            ):
                return version.id
        return None

    async def revise(
        self, version_id: int, payload: RevisionRequest
    ) -> ModerationDispatchResult | None:
        version = await self._get_version_for_update(version_id)
        if version is None:
            return None
        self._assert_no_pending_attempt(version)
        if version.document is None:
            raise ValueError("Document relation is required for revision")
        metadata, stage3 = self._ensure_stage3(version)
        versions = list(stage3.get("content_versions") or [])
        if self._is_restore_request(payload.comment) and len(versions) >= 2:
            restored = versions[-2]
            new_number = int(stage3["content_version"]) + 1
            versions.append(
                {
                    "version": new_number,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "created_by": "RESTORED_VERSION",
                    "revision_comment": payload.comment,
                    "reviewer": payload.reviewer,
                    "reviewer_id": payload.reviewer_id,
                    "restored_from_version": restored.get("version"),
                    "knowledge_base_article": restored.get("knowledge_base_article"),
                    "telegram_post": restored.get("telegram_post"),
                    "content_warnings": list(restored.get("content_warnings") or []),
                }
            )
            stage3.update(
                {
                    "status": PublicationStatus.READY_FOR_REVIEW.value,
                    "content_version": new_number,
                    "content_versions": versions,
                    "pending_revision": None,
                }
            )
            self._append_history(
                stage3,
                "CONTENT_RESTORED",
                actor=payload.reviewer,
                actor_id=payload.reviewer_id,
                content_version=new_number,
                restored_from_version=restored.get("version"),
                comment=payload.comment,
            )
            self._save_stage3(version, metadata, stage3)
            return await self.dispatch_to_moderation(version_id)
        if self.content_service is None:
            raise RuntimeError("AI content regeneration is not configured")
        stage2 = metadata.get("stage2") or {}
        analysis = FullAnalysisResult.model_validate(stage2.get("analysis") or {})
        current = self._current_content(version)
        previous = self._content_from_entry(versions[-2]) if len(versions) >= 2 else None
        stage_input = Stage2Input(
            source_code=str((metadata.get("source") or {}).get("code") or "unknown"),
            document_id=version.document_id,
            current_version_id=version.id,
            title=version.document.title,
            document_type=version.document.document_type,
            normalized_text=version.normalized_content,
            metadata=metadata,
            official_url=version.document.canonical_url,
        )
        generated, response = await self.content_service.generate(
            stage_input,
            analysis,
            revision_comment=payload.comment,
            current_content=current,
            previous_content=previous,
        )
        new_number = int(stage3["content_version"]) + 1
        versions.append(
            {
                "version": new_number,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "created_by": "AI_REVISION",
                "revision_comment": payload.comment,
                "reviewer": payload.reviewer,
                "reviewer_id": payload.reviewer_id,
                **generated.model_dump(mode="json"),
                "usage": response.usage.model_dump(mode="json"),
            }
        )
        stage3.update(
            {
                "status": PublicationStatus.READY_FOR_REVIEW.value,
                "content_version": new_number,
                "content_versions": versions,
                "pending_revision": None,
            }
        )
        self._append_history(
            stage3,
            "CONTENT_REGENERATED",
            actor=payload.reviewer,
            actor_id=payload.reviewer_id,
            content_version=new_number,
            comment=payload.comment,
        )
        self._save_stage3(version, metadata, stage3)
        return await self.dispatch_to_moderation(version_id)

    async def publish(
        self, version_id: int, payload: PublishRequest
    ) -> PublishActionResult | None:
        version = await self._get_version_for_update(version_id)
        return None if version is None else await self._publish_version(version, payload)

    async def _publish_version(
        self, version: DocumentVersion, payload: PublishRequest
    ) -> PublishActionResult:
        self._assert_publishable(version)
        if payload.target != "telegram":
            raise ValueError("Невідоме призначення публікації")
        if self._has_pending_attempt(version, "telegram"):
            return PublishActionResult(version_id=version.id, status=PublicationStatus.RECONCILIATION_REQUIRED,
                                      target="telegram", error="Результат попередньої спроби невідомий; потрібна звірка")
        status = self._status(version)
        if status == PublicationStatus.PUBLISHED:
            result = self._published_result(version, payload.target)
            if payload.include_knowledge_base and not payload.dry_run:
                kb = await self.publish_to_knowledge_base(version.id)
                result.knowledge_base_status = kb.status if kb else None
            return result
        if status != PublicationStatus.APPROVED:
            return PublishActionResult(
                version_id=version.id,
                status=PublicationStatus.FAILED,
                target=payload.target,
                error="Only APPROVED review items can be published",
            )
        metadata, stage3 = self._ensure_stage3(version)
        content = self._current_content(version)
        analysis = (version.version_metadata or {}).get("stage2", {}).get("analysis", {})
        channel_text = self.render_channel_post(
            content.telegram_post,
            title=version.document.title,
            source_url=version.document.canonical_url or analysis.get("official_source_url"),
            tags=self._hashtags(
                [label(value) for value in (analysis.get("topics") or analysis.get("categories") or [])]
            ),
        )
        if payload.dry_run:
            preview = await self.publisher.publish(
                version_id=version.id, text=channel_text, dry_run=True, parse_mode="HTML"
            )
            return PublishActionResult(version_id=version.id, status=PublicationStatus.APPROVED, target=preview.target, message_id=preview.message_id, published_at=preview.published_at)
        stage3["publication_choice"] = "TELEGRAM_WITH_KNOWLEDGE_BASE" if payload.include_knowledge_base else "TELEGRAM"
        self._save_stage3(version, metadata, stage3)
        publication_messages = list(stage3.get("publication_messages") or [])
        published_keys = {str(message.get("key")) for message in publication_messages}
        publication_prefix = f"v{stage3['content_version']}"
        short_key = f"{publication_prefix}:telegram_post"
        article_key_prefix = f"{publication_prefix}:knowledge_base_article:"
        publication_plan = [
            (short_key, channel_text, "HTML")
        ]
        last_result = None
        attempt_id = None
        content_number = int(stage3["content_version"])
        try:
            for key, text, parse_mode in publication_plan:
                if key in published_keys:
                    continue
                attempt_id = await self._start_attempt(version, "telegram", text)
                result = await self.publisher.publish(
                    version_id=version.id,
                    text=text,
                    dry_run=payload.dry_run,
                    parse_mode=parse_mode,
                )
                version, metadata, stage3 = await self._resume_attempt(version.id, "telegram", content_number, attempt_id)
                self._record_attempt_result(stage3, "telegram", content_number, "PUBLISHED")
                last_result = result
                publication_messages.append(
                    {
                        "key": key,
                        "message_id": result.message_id,
                        "target": result.target,
                        "published_at": result.published_at.isoformat(),
                    }
                )
                published_keys.add(key)
                stage3["publication_messages"] = publication_messages
                self._append_history(
                    stage3,
                    "PUBLICATION_PART_PUBLISHED",
                    key=key,
                    message_id=result.message_id,
                    target=result.target,
                )
                self._save_stage3(version, metadata, stage3)
        except Exception as exc:
            # Any unclassified error may follow successful external delivery.
            definite_failure = isinstance(exc, PublicationRejected)
            if attempt_id is not None:
                version, metadata, stage3 = await self._resume_attempt(version.id, "telegram", content_number, attempt_id)
                self._record_attempt_result(stage3, "telegram", content_number, "FAILED" if definite_failure else "UNKNOWN")
            error = "Помилка Telegram-публікації" if definite_failure else "Результат Telegram невідомий; потрібна звірка"
            failed_status = PublicationStatus.FAILED if definite_failure else PublicationStatus.RECONCILIATION_REQUIRED
            stage3.update(
                {
                    "status": failed_status.value,
                    "target": payload.target,
                    "error": error,
                    "failed_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            self._append_history(stage3, "PUBLICATION_FAILED", error=error)
            self._save_stage3(version, metadata, stage3)
            await self._checkpoint()
            return PublishActionResult(
                version_id=version.id,
                status=failed_status,
                target=payload.target,
                error=error,
            )
        if last_result is None:
            first = publication_messages[0]
            published_at = datetime.fromisoformat(str(first["published_at"]))
            target = str(first["target"])
        else:
            published_at = last_result.published_at
            target = last_result.target
        short_message = next(
            message for message in publication_messages if message.get("key") == short_key
        )
        article_message_ids = [
            str(message["message_id"])
            for message in publication_messages
            if str(message.get("key", "")).startswith(article_key_prefix)
        ]
        stage3.update(
            {
                "status": PublicationStatus.PUBLISHED.value,
                "target": target,
                "dry_run": payload.dry_run,
                "message_id": str(short_message["message_id"]),
                "article_message_ids": article_message_ids,
                "published_at": published_at.isoformat(),
                "error": None,
            }
        )
        self._append_history(
            stage3,
            "PUBLISHED",
            content_version=stage3["content_version"],
            message_id=str(short_message["message_id"]),
            article_message_ids=article_message_ids,
            target=target,
        )
        self._save_stage3(version, metadata, stage3)
        kb = None
        if not payload.dry_run:
            # Persist Telegram success before any independent adapter operation.
            await self._checkpoint()
            if payload.include_knowledge_base:
                kb = await self.publish_to_knowledge_base(version.id)
        return PublishActionResult(
            version_id=version.id,
            status=PublicationStatus.PUBLISHED,
            target=target,
            message_id=str(short_message["message_id"]),
            published_at=published_at,
            knowledge_base_status=kb.status if kb else None,
        )

    async def _set_decision(
        self,
        version_id: int,
        status: PublicationStatus,
        payload: ReviewDecisionRequest,
    ) -> ReviewDecisionResult | None:
        version = await self._get_version_for_update(version_id)
        return None if version is None else await self._set_decision_on_version(version, status, payload)

    async def _set_decision_on_version(
        self,
        version: DocumentVersion,
        status: PublicationStatus,
        payload: ReviewDecisionRequest,
    ) -> ReviewDecisionResult:
        self._assert_publishable(version)
        self._assert_no_pending_attempt(version)
        now = datetime.now(timezone.utc)
        metadata, stage3 = self._ensure_stage3(version)
        if self._status(version) == PublicationStatus.PUBLISHED:
            return ReviewDecisionResult(version_id=version.id, status=PublicationStatus.PUBLISHED, decided_at=now)
        stage3.update(
            {
                "status": status.value,
                "decided_at": now.isoformat(),
                "reviewer": payload.reviewer,
                "reviewer_id": payload.reviewer_id,
                "note": payload.note,
                "approved_content_version": stage3["content_version"]
                if status == PublicationStatus.APPROVED
                else None,
                "pending_revision": None,
            }
        )
        self._append_history(
            stage3,
            status.value,
            actor=payload.reviewer,
            actor_id=payload.reviewer_id,
            content_version=stage3["content_version"],
            note=payload.note,
        )
        self._save_stage3(version, metadata, stage3)
        return ReviewDecisionResult(
            version_id=version.id,
            status=status,
            decided_at=now,
            reviewer=payload.reviewer,
            note=payload.note,
        )

    def is_allowed(self, user_id: int) -> bool:
        return user_id in self.allowed_user_ids

    async def _checkpoint(self) -> None:
        session = getattr(self.repository, "session", None)
        if session is not None:
            await session.commit()

    @staticmethod
    def _has_pending_attempt(version: DocumentVersion, target: str) -> bool:
        stage3 = (version.version_metadata or {}).get("stage3") or {}
        key = f"{target}:{stage3.get('content_version', 1)}"
        return ((stage3.get("publication_attempts") or {}).get(key) or {}).get("status") in {"SENDING", "UNKNOWN"}

    def _assert_no_pending_attempt(self, version: DocumentVersion) -> None:
        if any(self._has_pending_attempt(version, target) for target in ("telegram", "knowledge_base")):
            raise ValueError("Спочатку звірте незавершену публікацію; редагування та рішення заблоковано")

    async def _start_attempt(self, version: DocumentVersion, target: str, text: str) -> str:
        metadata, stage3 = self._ensure_stage3(version)
        if self._has_pending_attempt(version, target):
            raise ValueError("Публікація вже має незавершену спробу")
        attempt_id = str(uuid4())
        attempts = dict(stage3.get("publication_attempts") or {})
        key = f"{target}:{stage3['content_version']}"
        attempts[key] = {"attempt_id": attempt_id, "status": "SENDING", "started_at": datetime.now(timezone.utc).isoformat(),
                         "content_hash": sha256(text.encode()).hexdigest(), "target": target,
                         "destination": getattr(self.publisher, "publication_channel_id", "telegram") if target == "telegram" else "knowledge_base"}
        stage3["publication_attempts"] = attempts
        self._append_history(stage3, "PUBLICATION_ATTEMPT_STARTED", key=key, attempt_id=attempt_id)
        self._save_stage3(version, metadata, stage3)
        # On crash, a durable SENDING marker prevents automatic redelivery.
        await self._checkpoint()
        return attempt_id

    async def _resume_attempt(self, version_id: int, target: str, content_version: int, attempt_id: str):
        version = await self._get_version_for_update(version_id)
        if version is None:
            raise ValueError("Матеріал не знайдено")
        metadata, stage3 = self._ensure_stage3(version)
        attempt = (stage3.get("publication_attempts") or {}).get(f"{target}:{content_version}") or {}
        if int(stage3["content_version"]) != content_version or attempt.get("attempt_id") != attempt_id or attempt.get("status") != "SENDING":
            raise ValueError("Стан спроби змінився; потрібна звірка")
        return version, metadata, stage3

    def _record_attempt_result(self, stage3: dict, target: str, content_version: int, status: str) -> None:
        attempts = dict(stage3.get("publication_attempts") or {})
        key = f"{target}:{content_version}"
        attempt = dict(attempts[key])
        attempt.update(status="SUCCEEDED" if status == "PUBLISHED" else "UNKNOWN" if status == "UNKNOWN" else "FAILED",
                       completed_at=datetime.now(timezone.utc).isoformat())
        attempts[key] = attempt
        stage3["publication_attempts"] = attempts
        self._append_history(stage3, "PUBLICATION_ATTEMPT_FINISHED", key=key, attempt_id=attempt["attempt_id"], status=attempt["status"])

    async def recover_publication(self, version_id: int, payload: PublicationRecoveryRequest) -> ReviewItemRead | None:
        version = await self._get_version_for_update(version_id)
        if version is None:
            return None
        metadata, stage3 = self._ensure_stage3(version)
        key = f"{payload.target}:{payload.content_version}"
        attempt = ((stage3.get("publication_attempts") or {}).get(key) or {})
        if int(stage3["content_version"]) != payload.content_version or attempt.get("attempt_id") != payload.attempt_id:
            raise ValueError("Спроба або редакція не відповідає запиту звірки")
        if attempt.get("status") not in {"SENDING", "UNKNOWN"}:
            raise ValueError("Спробу вже завершено")
        if attempt["status"] == "SENDING" and (datetime.now(timezone.utc) - datetime.fromisoformat(attempt["started_at"])).total_seconds() < 300:
            raise ValueError("Спроба ще може виконуватися; звірка SENDING доступна через 5 хвилин")
        if payload.outcome == "PUBLISHED" and not payload.reference_id:
            raise ValueError("Потрібен ідентифікатор знайденого повідомлення або сторінки")
        now = datetime.now(timezone.utc).isoformat()
        if payload.target == "telegram":
            if payload.outcome == "PUBLISHED":
                messages = list(stage3.get("publication_messages") or [])
                messages.append({"key": f"v{payload.content_version}:telegram_post", "message_id": payload.reference_id,
                                 "target": attempt["destination"], "published_at": now})
                stage3.update(publication_messages=messages, status="PUBLISHED", message_id=payload.reference_id,
                              target=attempt["destination"], published_at=now, error=None)
            else:
                stage3.update(status="APPROVED", error=None)
        else:
            publications = dict(stage3.get("knowledge_base_publications") or {})
            publications[str(payload.content_version)] = {**(publications.get(str(payload.content_version)) or {}), "status": "PUBLISHED" if payload.outcome == "PUBLISHED" else "FAILED",
                "page_id": payload.reference_id if payload.outcome == "PUBLISHED" else None, "page_url": payload.page_url,
                "published_at": now if payload.outcome == "PUBLISHED" else None, "content_version": payload.content_version}
            stage3["knowledge_base_publications"] = publications
        self._record_attempt_result(stage3, payload.target, payload.content_version, "PUBLISHED" if payload.outcome == "PUBLISHED" else "FAILED")
        self._append_history(stage3, "PUBLICATION_RECONCILED", key=key, attempt_id=payload.attempt_id,
                             outcome=payload.outcome, note=payload.note)
        self._save_stage3(version, metadata, stage3)
        await self._checkpoint()
        return self._to_review_item(version)

    @staticmethod
    def _assert_publishable(version: DocumentVersion) -> None:
        stage2 = (version.version_metadata or {}).get("stage2") or {}
        if stage2.get("status") != "ANALYZED" or (stage2.get("relevance") or {}).get("relevant") is False:
            raise ValueError("Публікацію заборонено: матеріал не пройшов аналіз і фільтрацію")

    async def _get_version_for_update(self, version_id: int) -> DocumentVersion | None:
        getter = getattr(self.repository, "get_version_for_update", self.repository.get_version)
        return await getter(version_id)

    def _ensure_stage3(self, version: DocumentVersion) -> tuple[dict[str, Any], dict[str, Any]]:
        metadata = dict(version.version_metadata or {})
        stage3 = dict(metadata.get("stage3") or {})
        if not stage3.get("content_versions"):
            content = (metadata.get("stage2") or {}).get("content") or {}
            stage3["content_version"] = 1
            stage3["content_versions"] = [
                {
                    "version": 1,
                    "created_at": (metadata.get("stage2") or {}).get("analyzed_at"),
                    "created_by": "STAGE2_AI",
                    "knowledge_base_article": content.get("knowledge_base_article"),
                    "telegram_post": content.get("telegram_post"),
                    "content_warnings": content.get("content_warnings") or [],
                }
            ]
        stage3.setdefault("content_version", 1)
        stage3.setdefault("status", PublicationStatus.READY_FOR_REVIEW.value)
        stage3.setdefault("history", [])
        return metadata, stage3

    def _current_content(self, version: DocumentVersion) -> ContentGenerationResult:
        metadata = version.version_metadata or {}
        versions = (metadata.get("stage3") or {}).get("content_versions") or []
        source = versions[-1] if versions else (metadata.get("stage2") or {}).get("content")
        return self._content_from_entry(source or {})

    def _content_from_entry(self, source: dict[str, Any]) -> ContentGenerationResult:
        return ContentGenerationResult.model_construct(
            knowledge_base_article=str(source.get("knowledge_base_article") or ""),
            telegram_post=str(source.get("telegram_post") or ""),
            content_warnings=list(source.get("content_warnings") or []),
        )

    @staticmethod
    def _split_publication_text(text: str, limit: int = 4000) -> list[str]:
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

    @staticmethod
    def _is_restore_request(comment: str) -> bool:
        normalized = " ".join(comment.casefold().split())
        exact = {"назад", "поверни назад", "зроби як було", "поверни як було"}
        phrases = (
            "поверни попередню версію",
            "віднови попередню версію",
            "відновити попередню версію",
            "скасуй останню правку",
            "відкоти останню правку",
        )
        return normalized in exact or any(phrase in normalized for phrase in phrases)

    def _save_stage3(
        self, version: DocumentVersion, metadata: dict[str, Any], stage3: dict[str, Any]
    ) -> None:
        metadata["stage3"] = stage3
        version.version_metadata = metadata

    def _append_history(self, stage3: dict[str, Any], event: str, **data: Any) -> None:
        history = list(stage3.get("history") or [])
        history.append({"event": event, "at": datetime.now(timezone.utc).isoformat(), **data})
        stage3["history"] = history

    def _published_result(self, version: DocumentVersion, target: str) -> PublishActionResult:
        stage3 = (version.version_metadata or {}).get("stage3") or {}
        return PublishActionResult(
            version_id=version.id,
            status=PublicationStatus.PUBLISHED,
            target=stage3.get("target") or target,
            message_id=stage3.get("message_id"),
            published_at=stage3.get("published_at"),
        )

    def _to_review_item(self, version: DocumentVersion) -> ReviewItemRead | None:
        metadata = version.version_metadata or {}
        stage2 = metadata.get("stage2") or {}
        if stage2.get("status") != "ANALYZED" or version.document is None:
            return None
        try:
            content = self._current_content(version)
        except Exception:
            return None
        analysis = stage2.get("analysis") or {}
        return ReviewItemRead(
            document_id=version.document_id,
            version_id=version.id,
            title=version.document.title,
            source_url=version.document.canonical_url,
            source_origin=urlparse(version.document.canonical_url or "").hostname,
            status=self._status(version),
            importance=analysis.get("importance"),
            categories=list(analysis.get("categories") or []),
            summary=analysis.get("summary"),
            document_status=analysis.get("document_status"),
            document_date=analysis.get("document_date"),
            source_published_at=version.document.published_at,
            effective_date=analysis.get("effective_date"),
            affected_entities=list(analysis.get("affected_entities") or []),
            practical_impact=analysis.get("practical_impact"),
            knowledge_base_recommendation=analysis.get("knowledge_base_recommendation") or {},
            telegram_post=content.telegram_post,
            knowledge_base_article=content.knowledge_base_article,
            review_metadata=metadata.get("stage3") or {},
        )

    def _render_moderation_card(self, item: ReviewItemRead, content_version: int) -> str:
        categories = ", ".join(label(x) for x in item.categories) or "не визначено"
        affected = ", ".join(label(x) for x in item.affected_entities) or "не визначено"
        source_published_date = (
            item.source_published_at.date().isoformat()
            if item.source_published_at
            else "не визначена"
        )
        text = (
            "МАТЕРІАЛ НА ПОГОДЖЕННЯ\n"
            f"Draft v{content_version}\n\n"
            "ТЕМА\n"
            f"{item.title[:200]}\n\n"
            "ПРЕВ'Ю ПУБЛІКАЦІЇ В КАНАЛІ\n"
            f"{self.render_channel_post(item.telegram_post)[:3000]}\n\n"
            "КЛЮЧОВІ ДАНІ\n"
            f"Важливість: {label(item.importance)}\n"
            f"Категорії: {categories}\n"
            f"Статус документа: {label(item.document_status)}\n"
            f"Дата документа: {item.document_date or 'не визначена'}\n"
            f"Дата публікації на джерелі: {source_published_date}\n"
            f"Набрання чинності: {item.effective_date or 'не визначено'}\n"
            f"Кого стосується: {affected}\n"
            f"Рекомендація щодо Бази: {label(item.knowledge_base_recommendation.recommendation.value)}\n"
            f"Причина рекомендації: {item.knowledge_base_recommendation.reason[:250]}\n"
            f"Сайт-джерело: {item.source_origin or 'не визначено'}\n"
            f"Офіційне джерело: {item.source_url or 'не вказано'}"
        )
        return text[:4096]

    @staticmethod
    def render_channel_post(
        text: str,
        *,
        title: str | None = None,
        source_url: str | None = None,
        tags: list[str] | None = None,
    ) -> str:
        body = ReviewService._clean_plain_markdown(text)
        if title and body.splitlines() and body.splitlines()[0].strip().casefold() == title.strip().casefold():
            body = "\n".join(body.splitlines()[1:]).lstrip()
        sections: list[str] = []
        if title:
            sections.append(f"<b>{html.escape(title.strip()[:250])}</b>")
        sections.append(html.escape(body[:3300]))
        if source_url:
            host = urlparse(source_url).hostname
            if source_url in body:
                source_line = f"Джерело: {host}" if host else "Джерело: офіційне посилання наведено вище"
            else:
                source_line = f"Джерело: {host} — {source_url}" if host else f"Джерело: {source_url}"
            sections.append(html.escape(source_line))
        if tags:
            hashtags = ReviewService._hashtags(tags)
            if hashtags:
                sections.append(" ".join(f"#{html.escape(tag)}" for tag in hashtags))
        return "\n\n".join(sections)[:4096]

    @staticmethod
    def _hashtags(values: list[str], limit: int = 3) -> list[str]:
        results: list[str] = []
        seen: set[str] = set()
        for value in values:
            words = re.findall(r"[\w]+", str(value), flags=re.UNICODE)
            tag = "_".join(words)[:35].strip("_")
            if tag and tag.casefold() not in seen:
                results.append(tag)
                seen.add(tag.casefold())
            if len(results) >= limit:
                break
        return results

    @staticmethod
    def render_full_article(text: str, *, include_header: bool = True) -> str:
        lines: list[str] = ["<b>Повна стаття</b>", ""] if include_header else []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            heading = re.match(r"^#{1,6}\s+(.+)$", line)
            if heading:
                if lines and lines[-1]:
                    lines.append("")
                lines.append(f"<b>{ReviewService._render_inline_html(heading.group(1))}</b>")
                lines.append("")
                continue
            if line.startswith("- "):
                line = f"• {line[2:]}"
            lines.append(ReviewService._render_inline_html(line))
        return ReviewService._normalize_blank_lines(lines)

    @staticmethod
    def _clean_plain_markdown(text: str) -> str:
        text = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1: \2", text)
        return text.replace("**", "").replace("__", "").strip()

    @staticmethod
    def _render_inline_html(text: str) -> str:
        pattern = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)|\*\*(.+?)\*\*")
        rendered: list[str] = []
        position = 0
        for match in pattern.finditer(text):
            rendered.append(html.escape(text[position : match.start()]))
            if match.group(1) is not None:
                label = html.escape(match.group(1))
                url = html.escape(match.group(2), quote=True)
                rendered.append(f'<a href="{url}">{label}</a>')
            else:
                rendered.append(f"<b>{html.escape(match.group(3))}</b>")
            position = match.end()
        rendered.append(html.escape(text[position:]))
        return "".join(rendered)

    @staticmethod
    def _normalize_blank_lines(lines: list[str]) -> str:
        normalized: list[str] = []
        for line in lines:
            if not line and normalized and not normalized[-1]:
                continue
            normalized.append(line)
        return "\n".join(normalized).strip()

    def _status(self, version: DocumentVersion) -> PublicationStatus:
        if self._has_pending_attempt(version, "telegram"):
            return PublicationStatus.RECONCILIATION_REQUIRED
        value = ((version.version_metadata or {}).get("stage3") or {}).get("status")
        try:
            return PublicationStatus(value or PublicationStatus.READY_FOR_REVIEW.value)
        except ValueError:
            return PublicationStatus.READY_FOR_REVIEW
