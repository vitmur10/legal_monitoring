from typing import Any

from app.ai.analysis_service import AIAnalysisService
from app.ai.provider import AIProvider, AIProviderError, AIResponse, UsageMetadata
from app.ai.relevance_service import AIRelevanceService
from app.ai.stage2_service import Stage2AnalysisService
from app.models.document import Document
from app.models.document_version import DocumentVersion
from app.models.enums import ProcessingStatus


class FakeProvider(AIProvider):
    def __init__(self, responses: list[dict[str, Any]], total_tokens: int = 10) -> None:
        self.responses = responses
        self.total_tokens = total_tokens
        self.calls: list[dict[str, Any]] = []

    async def structured_json(self, **kwargs) -> AIResponse:
        self.calls.append(kwargs)
        if not self.responses:
            raise AIProviderError("unexpected extra call")
        return AIResponse(
            data=self.responses.pop(0),
            usage=UsageMetadata(
                model="mock",
                request_type=kwargs["request_type"],
                total_tokens=self.total_tokens,
                document_id=kwargs["document_id"],
                version_id=kwargs["version_id"],
            ),
        )


def document() -> Document:
    return Document(
        id=1,
        source_id=1,
        identity_key="external_id:doc-1",
        identity_type="external_id",
        external_id="doc-1",
        canonical_url="https://example.test/doc-1",
        title="Зміни до декларації з ПДВ",
        document_type="order",
    )


def version(version_id: int, content: str) -> DocumentVersion:
    return DocumentVersion(
        id=version_id,
        document_id=1,
        version_number=version_id,
        raw_content=content,
        normalized_content=content,
        content_hash=f"hash-{version_id}",
        version_metadata={"official": True},
    )


def relevance(relevant: bool = True) -> dict[str, Any]:
    return {
        "relevant": relevant,
        "categories": ["VAT", "TAX_REPORTING"] if relevant else [],
        "reason": "Зміна строку подання декларації." if relevant else "Організаційна новина.",
        "confidence": 0.91,
    }


def analysis() -> dict[str, Any]:
    return {
        "relevant": True,
        "categories": ["VAT", "TAX_REPORTING"],
        "document_status": "EFFECTIVE",
        "document_date": "2026-04-07",
        "effective_date": "2026-04-15",
        "summary": "Змінено строк подання декларації.",
        "changes": [],
        "affected_entities": ["VAT_PAYERS"],
        "affected_entities_explanation": "Стосується платників ПДВ.",
        "practical_impact": "Потрібно оновити календар звітності.",
        "required_actions": ["Оновити внутрішній deadline для декларації."],
        "deadlines": [{"date": "2026-04-25", "description": "Новий строк подання."}],
        "risks": [{"type": "reporting", "description": "Ризик прострочення звітності."}],
        "importance": "HIGH",
        "importance_reason": "Зміна впливає на строк звітування.",
        "official_source_url": "https://example.test/doc-1",
        "missing_information": [],
        "confidence": 0.9,
    }


def service(provider: FakeProvider, token_limit: int | None = None) -> Stage2AnalysisService:
    return Stage2AnalysisService(
        relevance_service=AIRelevanceService(provider, "mock"),
        analysis_service=AIAnalysisService(provider, "mock"),
        max_total_tokens_per_document=token_limit,
    )


async def test_stage2_changed_builds_diff_and_runs_full_analysis() -> None:
    provider = FakeProvider([relevance(), analysis()])
    result = await service(provider).process(
        status=ProcessingStatus.CHANGED,
        document=document(),
        previous_version=version(10, "Пункт 1. Декларація подається до 20 числа."),
        current_version=version(11, "Пункт 1. Декларація подається до 25 числа."),
        source_code="dps",
    )

    assert result is not None
    assert result["status"] == "ANALYZED"
    assert result["diff"]["changed"] is True
    assert result["diff"]["changes"][0]["previous_text"].endswith("20 числа.")
    assert result["diff"]["changes"][0]["current_text"].endswith("25 числа.")
    assert result["analysis"]["summary"] == "Змінено строк подання декларації."
    assert [call["request_type"] for call in provider.calls] == ["relevance", "analysis"]


async def test_stage2_filtered_out_skips_full_analysis() -> None:
    provider = FakeProvider([relevance(False)])
    result = await service(provider).process(
        status=ProcessingStatus.NEW,
        document=document(),
        current_version=version(11, "Оголошено семінар для платників податків."),
        source_code="dps",
    )

    assert result is not None
    assert result["status"] == "FILTERED_OUT"
    assert result["analysis"] is None
    assert len(provider.calls) == 1


async def test_stage2_token_limit_stops_before_full_analysis() -> None:
    provider = FakeProvider([relevance(), analysis()], total_tokens=100)
    result = await service(provider, token_limit=100).process(
        status=ProcessingStatus.NEW,
        document=document(),
        current_version=version(11, "Пункт 1. Декларація подається до 25 числа."),
        source_code="dps",
    )

    assert result is not None
    assert result["status"] == "TOKEN_LIMIT_EXCEEDED"
    assert result["analysis"] is None
    assert result["usage"][0]["total_tokens"] == 100
    assert [call["request_type"] for call in provider.calls] == ["relevance"]


async def test_stage2_unchanged_returns_none() -> None:
    provider = FakeProvider([])
    result = await service(provider).process(
        status=ProcessingStatus.UNCHANGED,
        document=document(),
        current_version=version(11, "Пункт 1. Без змін."),
        source_code="dps",
    )

    assert result is None
    assert provider.calls == []
