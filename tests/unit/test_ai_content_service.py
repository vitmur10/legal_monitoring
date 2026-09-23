from typing import Any

from app.ai.content_service import AIContentService
from app.ai.provider import AIProvider, AIResponse, UsageMetadata
from app.ai.schemas import ContentGenerationResult, FullAnalysisResult, Stage2Input


class FakeProvider(AIProvider):
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = responses
        self.calls: list[dict[str, Any]] = []

    async def structured_json(self, **kwargs) -> AIResponse:
        self.calls.append(kwargs)
        return AIResponse(
            data=self.responses.pop(0),
            usage=UsageMetadata(
                model="mock",
                request_type=kwargs["request_type"],
                total_tokens=25,
            ),
        )


def stage_input() -> Stage2Input:
    return Stage2Input(
        source_code="dps",
        document_id=1,
        current_version_id=2,
        title="CRS 2.0",
        document_type="news",
        normalized_text="CRS 2.0 діє з 01.07.2026.",
        official_url="https://example.test",
    )


def analysis() -> FullAnalysisResult:
    return FullAnalysisResult.model_validate(
        {
            "relevant": True,
            "categories": ["CRS", "INTERNATIONAL_TAX"],
            "document_status": "EFFECTIVE",
            "document_date": "2026-06-15",
            "effective_date": "2026-07-01",
            "summary": "Оновлено правила CRS 2.0.",
            "changes": [
                {
                    "provision": "Порядок CRS",
                    "before": "Попередній порядок CRS.",
                    "after": "Оновлений порядок CRS 2.0.",
                    "explanation": "Фінансові установи мають оновити CRS-процеси.",
                    "evidence": [
                        {
                            "version_id": 2,
                            "text_excerpt": "наказ №316",
                            "source_url": "https://example.test",
                        }
                    ],
                }
            ],
            "affected_entities": ["FINANCIAL_INSTITUTIONS", "INTERNATIONAL_BUSINESS"],
            "affected_entities_explanation": "Стосується підзвітних фінансових установ.",
            "practical_impact": "Потрібно перевірити CRS onboarding і звітність.",
            "required_actions": ["Оновити CRS-процедури."],
            "deadlines": [{"date": "2026-07-01", "description": "Початок застосування."}],
            "risks": [{"type": "reporting", "description": "Ризик помилок у CRS-звітності."}],
            "importance": "HIGH",
            "importance_reason": "Вимоги вже чинні.",
            "official_source_url": "https://example.test",
            "missing_information": [],
            "confidence": 0.9,
        }
    )


def content_response() -> dict[str, Any]:
    return {
        "knowledge_base_article": (
            "CRS 2.0: що змінюється для фінансових установ\n\n"
            + (
                "З 1 липня 2026 року застосовуються оновлені правила CRS. "
                "Фінансовим установам потрібно перевірити onboarding, due diligence "
                "та підготовку звітності. "
            )
            * 20
            + "Джерело: https://example.test"
        ),
        "telegram_post": (
            "CRS 2.0: оновлення звітності для фінансових установ\n\n"
            "Оновлені правила застосовуються з 1 липня 2026 року.\n\n"
            "Що змінилося: оновлено порядок CRS 2.0.\n"
            "Кого стосується: підзвітних фінансових установ.\n"
            "Практичний вплив: потрібно перевірити процеси та звітність.\n"
            "Що зробити: перевірити CRS onboarding, due diligence та звітність.\n"
            "Дата: 01.07.2026.\n"
            "Джерело: https://example.test\n\n"
            "Зміни важливі для належної підготовки звітних процесів і перевірки "
            "внутрішніх процедур установи до наступного звітного циклу. Відповідальним "
            "підрозділам варто заздалегідь узгодити порядок виконання цих дій."
        ),
        "content_warnings": [],
    }


async def test_content_service_generates_article_and_telegram_post() -> None:
    provider = FakeProvider([content_response()])
    service = AIContentService(provider, model="mock")

    result, response = await service.generate(stage_input(), analysis())

    assert "CRS 2.0" in result.knowledge_base_article
    assert "01.07.2026" in result.telegram_post
    assert result.telegram_post.startswith("🔎 ")
    assert "📌 Що змінилося:" in result.telegram_post
    assert "👥 Кого стосується:" in result.telegram_post
    assert "🗓️ Дата:" in result.telegram_post
    assert "💡 Практичний вплив:" in result.telegram_post
    assert "✅ Що зробити:" in result.telegram_post
    assert "🔗 Джерело:" in result.telegram_post
    assert response.usage.request_type == "content_generation"
    assert provider.calls[0]["max_output_tokens"] == 2600


async def test_content_service_warns_when_sparse_source_yields_short_article() -> None:
    sparse = content_response()
    sparse["knowledge_base_article"] = "Наказ змінює форму декларації. " * 6
    provider = FakeProvider([sparse])
    short_input = stage_input().model_copy(update={"normalized_text": "Наказ № 313 змінює форму декларації."})
    service = AIContentService(provider, model="mock")

    result, _ = await service.generate(short_input, analysis())

    assert len(provider.calls) == 1
    assert result.content_warnings
    assert "повний текст документа" in result.content_warnings[0]


async def test_content_service_unwraps_nested_result() -> None:
    provider = FakeProvider([{"content": content_response()}])
    service = AIContentService(provider, model="mock")

    result, _ = await service.generate(stage_input(), analysis())

    assert result.content_warnings == []


async def test_revision_payload_contains_format_rules_and_previous_content() -> None:
    provider = FakeProvider([content_response()])
    service = AIContentService(provider, model="mock")
    current = ContentGenerationResult.model_validate(content_response())
    previous = ContentGenerationResult.model_validate(content_response())

    await service.generate(
        stage_input(),
        analysis(),
        revision_comment="Зміни тон на більш професійний",
        current_content=current,
        previous_content=previous,
    )

    payload = provider.calls[0]["user_payload"]
    assert payload["schema_version"] == "v6"
    assert payload["revision"]["previous_content"] == previous.model_dump(mode="json")
    assert payload["revision"]["current_lengths"]["knowledge_base_article"] > 0


async def test_content_service_retries_when_shorter_revision_is_not_shorter() -> None:
    current_data = content_response()
    current = ContentGenerationResult.model_validate(current_data)
    shorter = content_response()
    shorter["knowledge_base_article"] = current.knowledge_base_article[
        : int(len(current.knowledge_base_article) * 0.8)
    ]
    shorter["telegram_post"] = current.telegram_post.split("\n\nЗміни важливі", 1)[0]
    provider = FakeProvider([content_response(), shorter])
    service = AIContentService(provider, model="mock")

    result, _ = await service.generate(
        stage_input(),
        analysis(),
        revision_comment="Зроби текст коротшим",
        current_content=current,
    )

    assert len(provider.calls) == 2
    assert len(result.knowledge_base_article) < len(current.knowledge_base_article)
    assert len(result.telegram_post) < len(current.telegram_post)
    assert provider.calls[0]["user_payload"]["revision"]["length_requirement"][
        "direction"
    ] == "SHORTER"


async def test_content_service_retries_when_telegram_post_is_too_short() -> None:
    incomplete = content_response()
    incomplete["telegram_post"] = "Коротке повідомлення без обов'язкових блоків."
    provider = FakeProvider([incomplete, content_response()])
    service = AIContentService(provider, model="mock")

    result, _ = await service.generate(stage_input(), analysis())

    assert len(provider.calls) == 2
    assert "Що зробити:" in result.telegram_post
    assert "короткий текст потребує content_warnings" in provider.calls[1]["user_payload"]["validation_error"]


async def test_content_service_accepts_adaptive_headings_and_adds_official_source() -> None:
    adaptive = content_response()
    adaptive["telegram_post"] = (
        "Роз'яснення ДПС: первинні документи для ФОП\n\n"
        + "ФОП мають зберігати документи, що підтверджують облік доходів. "
        "Строк залежить від типу документів, а окремі випадки мають винятки. "
        * 8
    )
    provider = FakeProvider([adaptive])
    service = AIContentService(provider, model="mock")

    result, _ = await service.generate(stage_input(), analysis())

    assert len(provider.calls) == 1
    assert "Що змінилося:" not in result.telegram_post
    assert result.telegram_post.startswith("🔎 ")
    assert result.telegram_post.endswith("🔗 Джерело: https://example.test")
