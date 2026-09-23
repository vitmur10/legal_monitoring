import pytest
from pydantic import ValidationError

from app.ai.schemas import FullAnalysisResult, RelevanceResult


def test_relevance_schema_accepts_multiple_categories() -> None:
    result = RelevanceResult.model_validate(
        {
            "relevant": True,
            "categories": ["VAT", "TAX_REPORTING"],
            "reason": "Зміна стосується декларації з ПДВ.",
            "confidence": 0.91,
        }
    )

    assert [category.value for category in result.categories] == ["VAT", "TAX_REPORTING"]


def test_relevance_schema_rejects_invalid_confidence() -> None:
    with pytest.raises(ValidationError):
        RelevanceResult.model_validate(
            {
                "relevant": False,
                "categories": [],
                "reason": "Організаційна новина.",
                "confidence": 1.2,
            }
        )


def test_full_analysis_schema_handles_draft_without_effective_date() -> None:
    result = FullAnalysisResult.model_validate(
        {
            "relevant": True,
            "categories": ["CORPORATE_INCOME_TAX", "TAX_REPORTING"],
            "document_status": "DRAFT",
            "document_date": "2026-05-11",
            "effective_date": None,
            "summary": "Проект змінює форму декларації.",
            "changes": [
                {
                    "provision": None,
                    "before": None,
                    "after": "Запропоновано оновлену форму.",
                    "explanation": "Поки що це не чинна вимога.",
                    "evidence": [
                        {
                            "version_id": 1,
                            "text_excerpt": "проект наказу",
                            "source_url": "https://example.test",
                        }
                    ],
                }
            ],
            "affected_entities": ["CORPORATE_INCOME_TAX_PAYERS", "LEGAL_ENTITIES"],
            "affected_entities_explanation": "Стосується платників податку на прибуток.",
            "practical_impact": "Потрібно моніторити набрання чинності.",
            "required_actions": ["Моніторити прийняття документа."],
            "deadlines": [{"date": None, "description": "не визначено"}],
            "risks": [{"type": "reporting", "description": "Ризик майбутньої зміни звітності."}],
            "importance": "MEDIUM",
            "importance_reason": "Проект релевантний, але не чинний.",
            "official_source_url": "https://example.test",
            "missing_information": ["Дата набрання чинності не визначена."],
            "confidence": 0.84,
        }
    )

    assert result.document_status.value == "DRAFT"
    assert result.effective_date is None
    assert len(result.affected_entities) == 2


def test_full_analysis_schema_rejects_unknown_importance() -> None:
    with pytest.raises(ValidationError):
        FullAnalysisResult.model_validate(
            {
                "relevant": True,
                "categories": ["VAT"],
                "document_status": "EFFECTIVE",
                "summary": "Зміна.",
                "affected_entities_explanation": "Платники ПДВ.",
                "practical_impact": "Вплив.",
                "importance": "URGENT",
                "importance_reason": "Помилковий enum.",
                "confidence": 0.9,
            }
        )
