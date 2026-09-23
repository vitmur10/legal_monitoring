from datetime import datetime, timezone

from app.ai.provider import AIResponse, UsageMetadata
from app.ai.schemas import ContentGenerationResult, FullAnalysisResult, RelevanceResult
from app.ai.stage2_service import Stage2AnalysisService
from app.models.document import Document
from app.models.document_version import DocumentVersion
from app.models.enums import ProcessingStatus


class FakeRelevanceService:
    def __init__(self, relevant: bool = True) -> None:
        self.relevant = relevant

    async def classify(self, stage_input, diff=None):
        result = RelevanceResult.model_validate(
            {
                "relevant": self.relevant,
                "categories": ["CRS"] if self.relevant else [],
                "reason": "test",
                "confidence": 0.9,
            }
        )
        return result, response("relevance")


class FakeAnalysisService:
    async def analyze(self, stage_input, relevance, diff=None):
        return (
            FullAnalysisResult.model_validate(
                {
                    "relevant": True,
                    "categories": ["CRS"],
                    "document_status": "EFFECTIVE",
                    "document_date": "2026-06-15",
                    "effective_date": "2026-07-01",
                    "summary": "Оновлено правила CRS 2.0.",
                    "changes": [],
                    "affected_entities": ["FINANCIAL_INSTITUTIONS"],
                    "affected_entities_explanation": "Стосується фінансових установ.",
                    "practical_impact": "Потрібно оновити CRS-процеси.",
                    "required_actions": ["Перевірити CRS onboarding."],
                    "deadlines": [{"date": "2026-07-01", "description": "Початок дії."}],
                    "risks": [{"type": "reporting", "description": "Ризик помилок у CRS-звітності."}],
                    "importance": "HIGH",
                    "importance_reason": "Вимоги чинні.",
                    "official_source_url": "https://example.test",
                    "missing_information": [],
                    "confidence": 0.9,
                }
            ),
            response("analysis"),
        )


class FakeContentService:
    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, stage_input, analysis):
        self.calls += 1
        return (
            ContentGenerationResult(
                knowledge_base_article=(
                    "CRS 2.0: розгорнута стаття для Бази знань. "
                    "Описано статус, дату, кого стосується, практичний вплив, дії, ризики і джерело."
                ),
                telegram_post=(
                    "CRS 2.0: коротка Telegram-версія. Вимоги чинні з 01.07.2026. "
                    "Фінансовим установам варто перевірити CRS onboarding."
                ),
                content_warnings=[],
            ),
            response("content_generation"),
        )


def response(request_type: str) -> AIResponse:
    return AIResponse(
        data={},
        usage=UsageMetadata(model="mock", request_type=request_type, total_tokens=10),
    )


def document() -> Document:
    return Document(
        id=1,
        source_id=1,
        identity_key="doc",
        identity_type="external_id",
        external_id="doc",
        canonical_url="https://example.test",
        title="CRS 2.0",
        document_type="news",
        first_seen_at=datetime.now(timezone.utc),
        last_seen_at=datetime.now(timezone.utc),
    )


def version() -> DocumentVersion:
    return DocumentVersion(
        id=2,
        document_id=1,
        version_number=1,
        raw_content="raw",
        normalized_content="CRS 2.0 діє з 01.07.2026.",
        content_hash="hash",
        version_metadata={},
        detected_at=datetime.now(timezone.utc),
    )


async def test_stage2_generates_content_after_successful_analysis() -> None:
    content_service = FakeContentService()
    service = Stage2AnalysisService(
        relevance_service=FakeRelevanceService(),
        analysis_service=FakeAnalysisService(),
        content_service=content_service,
    )

    metadata = await service.process(
        status=ProcessingStatus.NEW,
        document=document(),
        current_version=version(),
        source_code="dps",
    )

    assert metadata is not None
    assert metadata["status"] == "ANALYZED"
    assert metadata["content"]["knowledge_base_article"]
    assert metadata["content"]["telegram_post"]
    assert [item["request_type"] for item in metadata["usage"]] == [
        "relevance",
        "analysis",
        "content_generation",
    ]
    assert content_service.calls == 1


async def test_stage2_does_not_generate_content_for_filtered_out_document() -> None:
    content_service = FakeContentService()
    service = Stage2AnalysisService(
        relevance_service=FakeRelevanceService(relevant=False),
        analysis_service=FakeAnalysisService(),
        content_service=content_service,
    )

    metadata = await service.process(
        status=ProcessingStatus.NEW,
        document=document(),
        current_version=version(),
        source_code="dps",
    )

    assert metadata is not None
    assert metadata["status"] == "FILTERED_OUT"
    assert metadata["content"] is None
    assert content_service.calls == 0
