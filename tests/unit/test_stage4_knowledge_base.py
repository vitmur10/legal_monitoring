import logging

import pytest
from pydantic import ValidationError

from app.ai.schemas import KnowledgeBaseRecommendationResult
from app.core.logging import SecretRedactingFormatter
from app.knowledge_base.service import KnowledgeBaseService, KnowledgeBasePublicationResult
from app.knowledge_base.errors import PublicationRejected
from app.notion.client import NotionClient
from app.stage3.publisher import TelegramBotClient
from app.stage3.review_service import ReviewService
from app.stage3.schemas import ReviewDecisionRequest, RevisionRequest
from app.stage3.telegram_service import TelegramWorkflowService
from tests.unit.test_stage3_telegram_workflow import (
    FakeRepository, FakeTelegram, FakeContentService, analyzed_version, callback,
)


class Adapter:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    async def publish(self, **payload):
        self.calls.append(payload)
        if self.fail:
            self.fail = False
            raise PublicationRejected("Bearer SECRET")
        return KnowledgeBasePublicationResult(status="PUBLISHED", page_id=f"page-{len(self.calls)}", page_url="https://example.test/page")


class ExistingNotionPage(NotionClient):
    def __init__(self, existing_date=None):
        super().__init__(token="test-only", database_id="test-only", enabled=True)
        self.existing_date = existing_date
        self.requests = []

    async def _request(self, method, path, payload):
        self.requests.append((method, path, payload))
        if method == "GET":
            return {"properties": {"Дата документа": {"type": "date", "date": self.existing_date}}}
        return {}


def setup(fail=False):
    version, telegram, adapter = analyzed_version(), FakeTelegram(), Adapter(fail)
    service = ReviewService(FakeRepository(version), telegram, moderation_client=telegram,
                            allowed_user_ids={77}, content_service=FakeContentService(),
                            knowledge_base_service=KnowledgeBaseService(adapter))
    return version, telegram, adapter, service, TelegramWorkflowService(service)


async def test_telegram_choice_and_later_addition():
    version, telegram, adapter, service, workflow = setup()
    await workflow.handle_update(callback("a"))
    assert telegram.publications == 1 and not adapter.calls
    await workflow.handle_update(callback("k"))
    await workflow.handle_update(callback("k"))
    await workflow.handle_update(callback("a"))
    assert telegram.publications == 1 and len(adapter.calls) == 1
    assert version.version_metadata["stage3"]["knowledge_base_publications"]["1"]["page_id"]


async def test_notion_uses_official_order_date_when_ai_analysis_omits_it():
    version, telegram, adapter, service, _ = setup()
    version.version_metadata["order_date"] = "2026-06-12"
    version.version_metadata["stage3"] = {"status": "PUBLISHED", "content_version": 1}

    result = await service.publish_to_knowledge_base(version.id)

    assert result.status == "PUBLISHED"
    assert adapter.calls[0]["analysis"]["document_date"] == "2026-06-12"


def test_public_channel_post_keeps_title_bold_and_includes_source():
    post = ReviewService.render_channel_post(
        "Короткий текст новини.",
        title="Назва матеріалу",
        source_url="https://mof.gov.ua/uk/orders",
        tags=["Податки"],
    )

    assert post.startswith("<b>Назва матеріалу</b>")
    assert "Короткий текст новини." in post
    formatted = ReviewService.render_channel_post(
        "📌 Що змінилося: Оновлено правила.\n"
        "👥 Кого стосується: Платників податків.\n"
        "🗓️ Коли діє: З 1 липня.\n"
        "💡 Практичний вплив: Треба оновити облік.\n"
        "✅ Що зробити: Перевірити процеси.",
        title="Назва матеріалу",
    )
    for heading in (
        "📌 <b>Що змінилося:</b>",
        "👥 <b>Кого стосується:</b>",
        "🗓️ <b>Коли діє:</b>",
        "💡 <b>Практичний вплив:</b>",
        "✅ <b>Що зробити:</b>",
    ):
        assert heading in formatted
    assert "🔗 <b>Джерело:</b> mof.gov.ua" in post
    assert "#Податки" in post


def test_public_channel_post_builds_bold_sections_from_structured_analysis():
    post = ReviewService.render_channel_post(
        "Загальний текст без структурованих підзаголовків.",
        title="Наказ про зміну форми декларації",
        source_url="https://mof.gov.ua/orders/313",
        tags=["Податки"],
        analysis={
            "summary": "Оновлено форму декларації з транспортного податку.",
            "changes": [{"explanation": "Змінено окремі поля форми."}],
            "affected_entities_explanation": "Платників транспортного податку.",
            "document_date": "2026-06-12",
            "practical_impact": "Під час звітування слід використовувати оновлену форму.",
            "required_actions": ["Перевірити актуальність форми перед поданням."],
        },
    )

    assert post.startswith("<b>Наказ про зміну форми декларації</b>")
    for heading in (
        "📌 <b>Що змінилося:</b>",
        "👥 <b>Кого стосується:</b>",
        "🗓️ <b>Коли діє:</b>",
        "💡 <b>Практичний вплив:</b>",
        "✅ <b>Що зробити:</b>",
        "🔗 <b>Джерело:</b>",
    ):
        assert heading in post
    assert "Змінено окремі поля форми." in post
    assert "Платників транспортного податку." in post
    assert "https://mof.gov.ua/orders/313" in post
    assert "Загальний текст без структурованих підзаголовків." not in post
    assert "#Податки" in post


async def test_combined_choice_retry_does_not_repeat_telegram():
    version, telegram, adapter, service, workflow = setup(fail=True)
    result = await workflow.handle_update(callback("b"))
    assert "База недоступна" in result.detail
    assert version.version_metadata["stage3"]["status"] == "PUBLISHED"
    assert version.version_metadata["stage3"]["knowledge_base_publications"]["1"]["status"] == "FAILED"
    await workflow.handle_update(callback("b"))
    await workflow.handle_update(callback("b"))
    assert telegram.publications == 1 and len(adapter.calls) == 2
    assert "SECRET" not in str(version.version_metadata)


async def test_new_content_revision_keeps_previous_page_and_links_it():
    version, telegram, adapter, service, workflow = setup()
    await workflow.handle_update(callback("b"))
    await service.request_revision(10, reviewer="reviewer", reviewer_id=77, chat_id="-1001")
    await service.revise(10, RevisionRequest(comment="Зробити коротше"))
    await service.approve_and_publish(10, ReviewDecisionRequest(), include_knowledge_base=True)
    await service.approve_and_publish(10, ReviewDecisionRequest(), include_knowledge_base=True)
    publications = version.version_metadata["stage3"]["knowledge_base_publications"]
    assert len(publications) == 2 and publications["1"]["page_id"] == "page-1"
    assert adapter.calls[-1]["previous_page_id"] == "page-1"
    assert telegram.publications == 2 and len(adapter.calls) == 2


@pytest.mark.parametrize("status", ["UNCHANGED", "FILTERED_OUT", "NO_MEANINGFUL_CHANGE"])
async def test_non_analyzed_material_cannot_be_published(status):
    version, telegram, adapter, service, workflow = setup()
    version.version_metadata["stage2"]["status"] = status
    with pytest.raises(ValueError):
        await service.approve_and_publish(10, ReviewDecisionRequest(), include_knowledge_base=True)
    with pytest.raises(ValueError):
        await service.publish_to_knowledge_base(10)
    assert telegram.publications == 0 and not adapter.calls


def test_structured_recommendation_validation():
    value = KnowledgeBaseRecommendationResult(recommendation="RECOMMENDED", reason="Має тривалу практичну цінність", confidence=.9)
    assert value.model_dump(mode="json")["recommendation"] == "RECOMMENDED"
    with pytest.raises(ValidationError):
        KnowledgeBaseRecommendationResult(confidence=1.1)


def test_ukrainian_notion_properties_and_full_article():
    client = NotionClient(token=None, database_id=None)
    payload = client._page_payload("Назва", {"importance": "HIGH", "document_status": "EXPLANATION", "categories": ["VAT"], "affected_entities": ["FOP"]}, "Стаття" * 1000, 1, 2, 1, "key", None, "old-page")
    props = payload["properties"]
    expected = ["Назва", "Дата документа", "Дата публікації джерела", "Номер документа", "Дата набрання чинності", "Дата початку застосування", "Статус документа", "Тип документа", "Орган", "Напрям", "Теми", "Кого стосується", "Що змінилося", "Практичний вплив", "Необхідні дії", "Строки", "Ризики", "Важливість", "Рекомендація щодо Бази", "Офіційне джерело", "Статус публікації", "Повний текст статті"]
    assert all(name in props for name in expected)
    assert props["Важливість"]["select"]["name"] == "Висока"
    assert props["Статус документа"]["select"]["name"] == "Офіційне роз’яснення"
    assert props["Кого стосується"]["multi_select"] == [{"name": "ФОП"}]
    payload = client._page_payload("Назва", {"source_published_at": "2026-09-09"}, "Текст статті", 1, 2, 1, "key", None, None)
    assert payload["properties"]["Дата публікації джерела"]["date"]["start"] == "2026-09-09"
    assert "".join(t["text"]["content"] for t in props["Повний текст статті"]["rich_text"]) == "Стаття" * 1000


async def test_notion_backfill_fills_only_an_empty_document_date():
    client = ExistingNotionPage()

    updated = await client.backfill_document_date_if_empty("page-1", "2026-06-12")

    assert updated is True
    assert client.requests[-1] == (
        "PATCH",
        "/pages/page-1",
        {"properties": {"Дата документа": {"date": {"start": "2026-06-12"}}}},
    )


async def test_notion_backfill_does_not_overwrite_an_existing_date():
    client = ExistingNotionPage({"start": "2026-06-13"})

    updated = await client.backfill_document_date_if_empty("page-1", "2026-06-12")

    assert updated is False
    assert [request[0] for request in client.requests] == ["GET"]


async def test_moderation_card_and_buttons():
    version, telegram, adapter, service, workflow = setup()
    version.version_metadata["stage2"]["content"]["content_warnings"] = [
        "Звірте матеріал із повним текстом наказу."
    ]
    item = (await service.list_items())[0]
    text = service._render_moderation_card(item, 1)
    for field in ["Статус документа", "Дата документа", "Дата публікації на джерелі", "Набрання чинності", "Важливість", "Кого стосується", "Рекомендація щодо Бази", "Причина рекомендації", "Сайт-джерело", "Офіційне джерело"]:
        assert field in text
    assert "Прийнятий" in text and "VAT_PAYERS" not in text
    assert "Звірте матеріал із повним текстом наказу." in text
    assert "<b>" not in text
    buttons = TelegramBotClient._review_markup(10, 1)["inline_keyboard"]
    assert {b["text"] for row in buttons for b in row} >= {"📢 Telegram", "📚 Telegram + База", "✏️ Виправити", "❌ Відхилити", "📚 Додати в Базу"}


def test_log_redaction():
    record = logging.LogRecord("test", logging.ERROR, "", 1, "https://api.telegram.org/bot123:secret/sendMessage Bearer NOTION_SECRET", (), None)
    result = SecretRedactingFormatter().format(record)
    assert "123:secret" not in result and "NOTION_SECRET" not in result


class RemoteNotion(NotionClient):
    def __init__(self):
        super().__init__(token="test-only", database_id="test-only", enabled=True)
        self.pages = {}
        self.creations = 0
        self.lose_response = False

    async def _request(self, method, path, payload):
        if path.endswith("/query"):
            key = payload["filter"]["rich_text"]["equals"]
            return {"results": [self.pages[key]] if key in self.pages else []}
        assert path == "/pages"
        self.creations += 1
        key = payload["properties"]["Ключ редакції"]["rich_text"][0]["text"]["content"]
        page = {"id": f"remote-{self.creations}", "url": "https://example.test/page"}
        self.pages[key] = page
        if self.lose_response:
            self.lose_response = False
            raise RuntimeError("response lost")
        return page


async def test_adapter_recovers_lost_response_and_new_revision_has_new_page():
    client = RemoteNotion()
    payload = dict(document_id=1, version_id=2, content_version=1, title="Тест",
                   analysis={}, article="Офіційний текст", telegram_message_id=None)
    client.lose_response = True
    assert (await client.publish(**payload)).status == "UNKNOWN"
    first = await client.publish(**payload)
    second = await client.publish(**payload)
    assert first.page_id == second.page_id and client.creations == 1
    newer = await client.publish(**{**payload, "content_version": 2})
    assert newer.page_id != first.page_id and client.creations == 2
