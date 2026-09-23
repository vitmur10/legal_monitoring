from datetime import datetime, timezone

from app.ai.provider import AIResponse, UsageMetadata
from app.ai.schemas import ContentGenerationResult
from app.models.document import Document
from app.models.document_version import DocumentVersion
from app.stage3.publisher import ModerationMessageResult, PublishResult
from app.stage3.review_service import ReviewService
from app.stage3.schemas import PublicationStatus, RevisionRequest
from app.stage3.telegram_service import TelegramWorkflowService
from app.knowledge_base.errors import PublicationRejected


class FakeRepository:
    def __init__(self, version: DocumentVersion) -> None:
        self.version = version

    async def list_versions_with_documents(self) -> list[DocumentVersion]:
        return [self.version]

    async def get_version(self, version_id: int) -> DocumentVersion | None:
        return self.version if version_id == self.version.id else None

    async def get_version_for_update(self, version_id: int) -> DocumentVersion | None:
        return await self.get_version(version_id)


class FakeTelegram:
    def __init__(
        self,
        *,
        fail_first_publication: bool = False,
        fail_on_publication: int | None = None,
    ) -> None:
        self.cards = 0
        self.publications = 0
        self.published_texts: list[str] = []
        self.answers: list[str] = []
        self.messages: list[str] = []
        self.message_actions: list[tuple[int | None, int | None]] = []
        self.fail_first_publication = fail_first_publication
        self.fail_on_publication = fail_on_publication

    async def send_moderation_card(self, **kwargs) -> ModerationMessageResult:
        self.cards += 1
        return ModerationMessageResult(
            chat_id="-1001",
            message_id=str(100 + self.cards),
            sent_at=datetime.now(timezone.utc),
        )

    async def publish(
        self,
        *,
        version_id: int,
        text: str,
        dry_run: bool = True,
        parse_mode: str | None = None,
    ) -> PublishResult:
        self.publications += 1
        self.published_texts.append(text)
        if (self.fail_first_publication and self.publications == 1) or (
            self.fail_on_publication == self.publications
        ):
            raise PublicationRejected("Telegram rejected request without delivery")
        return PublishResult(
            target="@test_channel",
            message_id=str(200 + self.publications),
            published_at=datetime.now(timezone.utc),
        )

    async def answer_callback(self, callback_query_id: str, text: str) -> None:
        self.answers.append(text)

    async def send_text(
        self,
        *,
        chat_id: str,
        text: str,
        force_reply: bool = False,
        review_version_id: int | None = None,
        content_version: int | None = None,
        parse_mode: str | None = None,
    ) -> str:
        self.messages.append(text)
        self.message_actions.append((review_version_id, content_version))
        return "300"


class FakeContentService:
    async def generate(self, stage_input, analysis, **kwargs):
        assert kwargs["revision_comment"] == "Зробити коротше"
        content = ContentGenerationResult(
            knowledge_base_article="Оновлена розгорнута стаття для бази знань. " * 3,
            telegram_post="Оновлений короткий Telegram-допис після правки редактора.",
        )
        response = AIResponse(
            data=content.model_dump(),
            usage=UsageMetadata(model="fake", request_type="content_generation"),
        )
        return content, response


def analyzed_version() -> DocumentVersion:
    document = Document(
        id=1,
        source_id=1,
        identity_key="case",
        identity_type="external_id",
        canonical_url="https://example.com/law",
        title="Тестова зміна",
        first_seen_at=datetime.now(timezone.utc),
        last_seen_at=datetime.now(timezone.utc),
    )
    version = DocumentVersion(
        id=10,
        document_id=1,
        version_number=1,
        raw_content="raw",
        normalized_content="normalized legal content",
        content_hash="hash",
        detected_at=datetime.now(timezone.utc),
        version_metadata={
            "stage2": {
                "status": "ANALYZED",
                "analyzed_at": datetime.now(timezone.utc).isoformat(),
                "analysis": {
                    "relevant": True,
                    "categories": ["VAT"],
                    "document_status": "ADOPTED",
                    "document_date": None,
                    "effective_date": None,
                    "summary": "Змінено правила ПДВ.",
                    "changes": [],
                    "affected_entities": ["VAT_PAYERS"],
                    "affected_entities_explanation": "Платники ПДВ.",
                    "practical_impact": "Потрібно оновити процес.",
                    "required_actions": ["Перевірити налаштування"],
                    "deadlines": [],
                    "risks": [],
                    "importance": "HIGH",
                    "importance_reason": "Впливає на звітність.",
                    "official_source_url": "https://example.com/law",
                    "missing_information": [],
                    "confidence": 0.9,
                },
                "content": {
                    "knowledge_base_article": "Початкова розгорнута стаття для бази знань. " * 3,
                    "telegram_post": "Початковий короткий Telegram-допис про зміну правил ПДВ.",
                    "content_warnings": [],
                },
            }
        },
    )
    version.document = document
    return version


def callback(action: str, *, user_id: int = 77) -> dict:
    return {
        "callback_query": {
            "id": "callback-1",
            "from": {"id": user_id, "username": "reviewer"},
            "message": {"chat": {"id": -1001}},
            "data": f"s3:{action}:10:1",
        }
    }


async def test_dispatch_is_idempotent_for_same_content_version() -> None:
    telegram = FakeTelegram()
    service = ReviewService(
        FakeRepository(analyzed_version()), telegram, moderation_client=telegram
    )

    first = await service.dispatch_to_moderation(10)
    second = await service.dispatch_to_moderation(10)

    assert first.message_id == second.message_id
    assert telegram.cards == 1


async def test_unlisted_user_cannot_make_decision() -> None:
    telegram = FakeTelegram()
    service = ReviewService(
        FakeRepository(analyzed_version()),
        telegram,
        moderation_client=telegram,
        allowed_user_ids={77},
    )

    result = await TelegramWorkflowService(service).handle_update(callback("a", user_id=99))

    assert result.action == "FORBIDDEN"
    assert telegram.publications == 0


async def test_view_article_sends_current_full_content() -> None:
    telegram = FakeTelegram()
    service = ReviewService(
        FakeRepository(analyzed_version()),
        telegram,
        moderation_client=telegram,
        allowed_user_ids={77},
    )

    result = await TelegramWorkflowService(service).handle_update(callback("v"))

    assert result.action == "VIEW_ARTICLE"
    assert result.status == PublicationStatus.READY_FOR_REVIEW
    assert telegram.publications == 0
    assert telegram.messages
    assert telegram.messages[0].startswith("<b>Версія для погодження: Draft v1</b>")
    assert "Початкова розгорнута стаття" in telegram.messages[0]
    assert telegram.message_actions[-1] == (10, 1)


async def test_repeated_approve_callback_publishes_only_once() -> None:
    version = analyzed_version()
    telegram = FakeTelegram()
    service = ReviewService(
        FakeRepository(version),
        telegram,
        moderation_client=telegram,
        allowed_user_ids={77},
    )
    workflow = TelegramWorkflowService(service)

    first = await workflow.handle_update(callback("a"))
    second = await workflow.handle_update(callback("a"))

    assert first.status == PublicationStatus.PUBLISHED
    assert second.status == PublicationStatus.PUBLISHED
    assert telegram.publications == 1
    assert version.version_metadata["stage3"]["message_id"] == "201"
    assert version.version_metadata["stage3"]["article_message_ids"] == []
    assert "<b>" not in telegram.published_texts[0]
    assert len(telegram.published_texts) == 1


async def test_revision_comment_creates_new_ai_content_version_and_card() -> None:
    version = analyzed_version()
    telegram = FakeTelegram()
    service = ReviewService(
        FakeRepository(version),
        telegram,
        moderation_client=telegram,
        content_service=FakeContentService(),
        allowed_user_ids={77},
    )
    workflow = TelegramWorkflowService(service)

    requested = await workflow.handle_update(callback("e"))
    revised = await workflow.handle_update(
        {
            "message": {
                "from": {"id": 77, "username": "reviewer"},
                "chat": {"id": -1001},
                "text": "/fix Зробити коротше",
            }
        }
    )

    stage3 = version.version_metadata["stage3"]
    assert requested.status == PublicationStatus.REVISION_REQUESTED
    assert revised.status == PublicationStatus.READY_FOR_REVIEW
    assert stage3["content_version"] == 2
    assert len(stage3["content_versions"]) == 2
    assert stage3["content_versions"][1]["revision_comment"] == "Зробити коротше"
    assert telegram.cards == 1
    assert [item["event"] for item in stage3["history"]] == [
        "REVISION_REQUESTED",
        "CONTENT_REGENERATED",
        "SENT_FOR_REVIEW",
    ]


async def test_restore_comment_creates_copy_of_previous_content_version() -> None:
    version = analyzed_version()
    telegram = FakeTelegram()
    service = ReviewService(
        FakeRepository(version),
        telegram,
        moderation_client=telegram,
        content_service=FakeContentService(),
        allowed_user_ids={77},
    )
    workflow = TelegramWorkflowService(service)

    await workflow.handle_update(callback("e"))
    await workflow.handle_update(
        {
            "message": {
                "from": {"id": 77, "username": "reviewer"},
                "chat": {"id": -1001},
                "text": "/fix Зробити коротше",
            }
        }
    )
    await service.request_revision(10, reviewer="reviewer", reviewer_id=77, chat_id="-1001")
    restored = await service.revise(
        10,
        RevisionRequest(
            reviewer="reviewer",
            reviewer_id=77,
            comment="Поверни попередню версію",
        ),
    )

    stage3 = version.version_metadata["stage3"]
    assert restored.status == PublicationStatus.READY_FOR_REVIEW
    assert stage3["content_version"] == 3
    assert stage3["content_versions"][2]["created_by"] == "RESTORED_VERSION"
    assert stage3["content_versions"][2]["restored_from_version"] == 1
    assert (
        stage3["content_versions"][2]["knowledge_base_article"]
        == stage3["content_versions"][0]["knowledge_base_article"]
    )


async def test_failed_publication_can_be_retried_without_false_published_status() -> None:
    version = analyzed_version()
    telegram = FakeTelegram(fail_first_publication=True)
    service = ReviewService(
        FakeRepository(version),
        telegram,
        moderation_client=telegram,
        allowed_user_ids={77},
    )
    workflow = TelegramWorkflowService(service)

    failed = await workflow.handle_update(callback("a"))
    retried = await workflow.handle_update(callback("a"))

    assert failed.status == PublicationStatus.FAILED
    assert retried.status == PublicationStatus.PUBLISHED
    assert telegram.publications == 2
    assert [entry["event"] for entry in version.version_metadata["stage3"]["history"] if not entry["event"].startswith("PUBLICATION_ATTEMPT_")] == [
        "APPROVED",
        "PUBLICATION_FAILED",
        "APPROVED",
        "PUBLICATION_PART_PUBLISHED",
        "PUBLISHED",
    ]


async def test_full_article_is_never_sent_to_publication_channel() -> None:
    version = analyzed_version()
    telegram = FakeTelegram(fail_on_publication=2)
    service = ReviewService(
        FakeRepository(version),
        telegram,
        moderation_client=telegram,
        allowed_user_ids={77},
    )
    workflow = TelegramWorkflowService(service)

    failed = await workflow.handle_update(callback("a"))
    retried = await workflow.handle_update(callback("a"))

    assert failed.status == PublicationStatus.PUBLISHED
    assert retried.status == PublicationStatus.PUBLISHED
    assert telegram.publications == 1
    messages = version.version_metadata["stage3"]["publication_messages"]
    assert [message["key"] for message in messages] == [
        "v1:telegram_post",
    ]
