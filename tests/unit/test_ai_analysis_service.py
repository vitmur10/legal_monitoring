from typing import Any

from app.ai.analysis_service import AIAnalysisService
from app.ai.provider import AIProvider, AIResponse, UsageMetadata
from app.ai.schemas import RelevanceResult, Stage2Input
from app.diff.engine import DocumentDiffEngine


class FakeProvider(AIProvider):
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    async def structured_json(self, **kwargs) -> AIResponse:
        self.calls.append(kwargs)
        return AIResponse(
            data=self.response,
            usage=UsageMetadata(model="mock", request_type=kwargs["request_type"], total_tokens=20),
        )


def stage_input() -> Stage2Input:
    return Stage2Input(
        source_code="dps",
        document_id=1,
        previous_version_id=10,
        current_version_id=11,
        title="Зміни до декларації з ПДВ",
        document_type="order",
        normalized_text="Пункт 1. Декларація подається до 20 числа.",
        official_url="https://example.test/doc",
    )


def relevance() -> RelevanceResult:
    return RelevanceResult(
        relevant=True,
        categories=["VAT", "TAX_REPORTING"],
        reason="Зміна стосується звітності з ПДВ.",
        confidence=0.92,
    )


def analysis_response() -> dict[str, Any]:
    return {
        "relevant": True,
        "categories": ["VAT", "TAX_REPORTING"],
        "document_status": "EFFECTIVE",
        "document_date": "2026-04-07",
        "effective_date": "2026-04-15",
        "summary": "Змінено строк подання декларації.",
        "changes": [
            {
                "provision": "Пункт 1",
                "before": "до 20 числа",
                "after": "до 25 числа",
                "explanation": "Строк подання продовжено.",
                "evidence": [
                    {
                        "version_id": 11,
                        "text_excerpt": "Декларація подається до 25 числа.",
                        "source_url": "https://example.test/doc",
                    }
                ],
            }
        ],
        "affected_entities": ["VAT_PAYERS"],
        "affected_entities_explanation": "Стосується платників ПДВ.",
        "practical_impact": "Потрібно оновити календар звітності.",
        "required_actions": ["Оновити внутрішній deadline для декларації."],
        "deadlines": [{"date": "2026-04-25", "description": "Новий строк подання."}],
        "risks": [{"type": "reporting", "description": "Ризик прострочення звітності."}],
        "importance": "HIGH",
        "importance_reason": "Зміна впливає на строк звітування.",
        "official_source_url": "https://example.test/doc",
        "missing_information": [],
        "confidence": 0.91,
    }


async def test_analysis_service_uses_diff_before_after_text() -> None:
    diff = DocumentDiffEngine().build(
        document_id=1,
        previous_version_id=10,
        current_version_id=11,
        previous_text="Пункт 1. Декларація подається до 20 числа.",
        current_text="Пункт 1. Декларація подається до 25 числа.",
    )
    provider = FakeProvider(analysis_response())
    service = AIAnalysisService(provider, model="mock", max_output_tokens=1234)

    result, response = await service.analyze(stage_input(), relevance(), diff)

    payload = provider.calls[0]["user_payload"]
    assert "Було:" in payload["normalized_text"]
    assert "Стало:" in payload["normalized_text"]
    assert "до 20 числа" in payload["normalized_text"]
    assert "до 25 числа" in payload["normalized_text"]
    assert provider.calls[0]["max_output_tokens"] == 1234
    assert result.importance.value == "HIGH"
    assert response.usage.total_tokens == 20
