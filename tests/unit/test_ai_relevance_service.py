from typing import Any

import pytest

from app.ai.provider import AIProvider, AIResponse, UsageMetadata
from app.ai.relevance_service import AIRelevanceService
from app.ai.schemas import Stage2Input


class FakeProvider(AIProvider):
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = responses
        self.calls: list[dict[str, Any]] = []

    async def structured_json(self, **kwargs) -> AIResponse:
        self.calls.append(kwargs)
        return AIResponse(
            data=self.responses.pop(0),
            usage=UsageMetadata(model="mock", request_type=kwargs["request_type"], total_tokens=5),
        )


def stage_input() -> Stage2Input:
    return Stage2Input(
        source_code="dps",
        document_id=1,
        current_version_id=2,
        title="Податкова новина",
        document_type="news",
        normalized_text="Змінено правила подання декларації з ПДВ.",
        official_url="https://example.test",
    )


@pytest.mark.parametrize(
    ("response", "decision", "band"),
    [
        (
            {
                "relevant": True,
                "categories": ["VAT", "TAX_REPORTING"],
                "reason": "Зміна правил звітності.",
                "confidence": 0.91,
            },
            "relevant",
            "auto_decision",
        ),
        (
            {
                "relevant": False,
                "categories": [],
                "reason": "Повідомлення про зустріч без зміни правил.",
                "confidence": 0.83,
            },
            "filtered_out",
            "auto_decision",
        ),
        (
            {
                "relevant": True,
                "categories": ["OTHER_RELEVANT"],
                "reason": "Ймовірно релевантно, але бракує контексту.",
                "confidence": 0.42,
            },
            "relevant",
            "low_confidence",
        ),
    ],
)
async def test_relevance_service_adds_decision_metadata(
    response: dict[str, Any], decision: str, band: str
) -> None:
    service = AIRelevanceService(FakeProvider([response]), model="mock")

    result, _ = await service.classify(stage_input())

    assert result.decision_metadata is not None
    assert result.decision_metadata.decision == decision
    assert result.decision_metadata.confidence_band == band


async def test_relevance_service_retries_once_on_schema_validation_error() -> None:
    provider = FakeProvider(
        [
            {"relevant": True, "categories": "VAT", "reason": "bad", "confidence": 0.9},
            {
                "relevant": True,
                "categories": ["VAT"],
                "reason": "Зміна правил ПДВ.",
                "confidence": 0.9,
            },
        ]
    )
    service = AIRelevanceService(provider, model="mock")

    result, _ = await service.classify(stage_input())

    assert result.relevant is True
    assert len(provider.calls) == 2
    assert "validation_error" in provider.calls[1]["user_payload"]
