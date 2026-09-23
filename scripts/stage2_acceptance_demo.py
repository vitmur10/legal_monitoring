import asyncio
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.ai.analysis_service import AIAnalysisService
from app.ai.provider import AIProvider, AIResponse, UsageMetadata
from app.ai.relevance_service import AIRelevanceService
from app.ai.stage2_service import Stage2AnalysisService
from app.models.document import Document
from app.models.document_version import DocumentVersion
from app.models.enums import ProcessingStatus


class DemoProvider(AIProvider):
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = responses
        self.calls: list[dict[str, Any]] = []

    async def structured_json(self, **kwargs) -> AIResponse:
        self.calls.append(kwargs)
        if not self.responses:
            raise RuntimeError("DemoProvider response queue is empty")
        return AIResponse(
            data=self.responses.pop(0),
            usage=UsageMetadata(
                model="demo",
                request_type=kwargs["request_type"],
                document_id=kwargs["document_id"],
                version_id=kwargs["version_id"],
                total_tokens=100,
            ),
        )


CASES = [
    {
        "name": "Law 4835-IX",
        "source_code": "rada",
        "document": {
            "id": 1,
            "external_id": "4835-IX",
            "canonical_url": "https://zakon.rada.gov.ua/laws/show/4835-20#Text",
            "title": "Закон України No. 4835-IX",
            "document_type": "law",
        },
        "previous_text": (
            "Пункт 16-1. Військовий збір застосовується до 31 грудня року, "
            "у якому припинено або скасовано воєнний стан."
        ),
        "current_text": (
            "Пункт 16-1. Військовий збір застосовується до 31 грудня третього "
            "календарного року, наступного за роком припинення або скасування воєнного стану."
        ),
        "relevance": {
            "relevant": True,
            "categories": ["MILITARY_TAX", "PIT", "TAX_REPORTING"],
            "reason": "Зміна строку застосування військового збору.",
            "confidence": 0.96,
        },
        "analysis": {
            "relevant": True,
            "categories": ["MILITARY_TAX", "PIT", "TAX_REPORTING"],
            "document_status": "EFFECTIVE",
            "document_date": "2026-04-07",
            "effective_date": "2026-04-15",
            "summary": "Продовжено строк застосування правил військового збору.",
            "changes": [
                {
                    "provision": "п. 16-1 підрозділу 10 розділу XX ПКУ",
                    "before": "Строк був прив'язаний до року завершення воєнного стану.",
                    "after": "Строк продовжено до третього наступного календарного року.",
                    "explanation": "Payroll/tax withholding процеси треба підтримувати довше.",
                    "evidence": [
                        {
                            "version_id": 2,
                            "text_excerpt": "до 31 грудня третього календарного року",
                            "source_url": "https://zakon.rada.gov.ua/laws/show/4835-20#Text",
                        }
                    ],
                }
            ],
            "affected_entities": ["EMPLOYERS", "TAX_AGENTS", "ALL_TAXPAYERS"],
            "affected_entities_explanation": "Стосується податкових агентів і роботодавців.",
            "practical_impact": "Потрібно підтримувати налаштування військового збору.",
            "required_actions": ["Оновити payroll/tax календарі після завершення воєнного стану."],
            "deadlines": [{"date": None, "description": "Залежить від завершення воєнного стану."}],
            "risks": [{"type": "tax", "description": "Ризик неправильного утримання збору."}],
            "importance": "HIGH",
            "importance_reason": "Зміна чинна і впливає на податкове адміністрування.",
            "official_source_url": "https://zakon.rada.gov.ua/laws/show/4835-20#Text",
            "missing_information": [],
            "confidence": 0.94,
        },
    },
    {
        "name": "Minfin Order 293 + DPS letter",
        "source_code": "dps",
        "document": {
            "id": 2,
            "external_id": "80200",
            "canonical_url": "https://tax.gov.ua/zakonodavstvo/podatkove-zakonodavstvo/listi-dps/80200.html",
            "title": "Лист ДПС щодо змін до декларації з податку на прибуток",
            "document_type": "explanation",
        },
        "previous_text": "Декларація з податку на прибуток подається за попередньою формою.",
        "current_text": (
            "Декларацію з податку на прибуток доповнено рядком 02.1 ЄП і додатком ЄП "
            "для окремих платників єдиного податку четвертої групи."
        ),
        "relevance": {
            "relevant": True,
            "categories": ["CORPORATE_INCOME_TAX", "TAX_REPORTING", "SINGLE_TAX"],
            "reason": "Зміна форми податкової декларації.",
            "confidence": 0.95,
        },
        "analysis": {
            "relevant": True,
            "categories": ["CORPORATE_INCOME_TAX", "TAX_REPORTING", "SINGLE_TAX"],
            "document_status": "EXPLANATION",
            "document_date": "2026-07-08",
            "effective_date": None,
            "summary": "ДПС роз'яснює оновлення декларації з податку на прибуток.",
            "changes": [
                {
                    "provision": "форма декларації з податку на прибуток підприємств",
                    "before": "Форма не містила рядка 02.1 ЄП і додатка ЄП.",
                    "after": "Форму доповнено рядком 02.1 ЄП і додатком ЄП.",
                    "explanation": "Потрібна readiness облікової системи до нових полів.",
                    "evidence": [
                        {
                            "version_id": 2,
                            "text_excerpt": "рядком 02.1 ЄП і додатком ЄП",
                            "source_url": "https://tax.gov.ua/zakonodavstvo/podatkove-zakonodavstvo/listi-dps/80200.html",
                        }
                    ],
                }
            ],
            "affected_entities": ["CORPORATE_INCOME_TAX_PAYERS", "SINGLE_TAX_PAYERS"],
            "affected_entities_explanation": "Стосується платників податку на прибуток і ЄП 4 групи.",
            "practical_impact": "Потрібно перевірити шаблони декларації та облікову систему.",
            "required_actions": ["Оновити або перевірити шаблони декларації."],
            "deadlines": [{"date": None, "description": "Дата застосування з тексту не визначена."}],
            "risks": [{"type": "reporting", "description": "Ризик подання за неактуальною формою."}],
            "importance": "HIGH",
            "importance_reason": "Зміна впливає на форму звітності.",
            "official_source_url": "https://tax.gov.ua/zakonodavstvo/podatkove-zakonodavstvo/listi-dps/80200.html",
            "missing_information": ["Точна дата першого звітного періоду застосування."],
            "confidence": 0.91,
        },
    },
    {
        "name": "CRS 2.0 Minfin Order 316",
        "source_code": "minfin",
        "document": {
            "id": 3,
            "external_id": "order-316",
            "canonical_url": "https://www.mof.gov.ua/uk/crs-578",
            "title": "Наказ Мінфіну No. 316 щодо CRS 2.0",
            "document_type": "order",
        },
        "previous_text": "Порядок CRS застосовується до фінансових рахунків.",
        "current_text": (
            "Порядок CRS оновлено для CRS 2.0, включно з електронними грошима, "
            "CBDC та віртуальними активами. Застосування з 1 липня 2026 року."
        ),
        "relevance": {
            "relevant": True,
            "categories": ["CRS", "INTERNATIONAL_TAX", "EU_TAX_INTEGRATION"],
            "reason": "Зміна міжнародної податкової звітності CRS.",
            "confidence": 0.97,
        },
        "analysis": {
            "relevant": True,
            "categories": ["CRS", "INTERNATIONAL_TAX", "EU_TAX_INTEGRATION"],
            "document_status": "EFFECTIVE",
            "document_date": "2026-06-15",
            "effective_date": "2026-07-01",
            "summary": "Оновлено правила CRS з урахуванням CRS 2.0.",
            "changes": [
                {
                    "provision": "Порядок застосування CRS",
                    "before": "Порядок не охоплював повний набір цифрових продуктів CRS 2.0.",
                    "after": "Додано електронні гроші, CBDC та віртуальні активи.",
                    "explanation": "Фінустанови мають переглянути due diligence і звітність.",
                    "evidence": [
                        {
                            "version_id": 2,
                            "text_excerpt": "електронними грошима, CBDC та віртуальними активами",
                            "source_url": "https://www.mof.gov.ua/uk/crs-578",
                        }
                    ],
                }
            ],
            "affected_entities": ["FINANCIAL_INSTITUTIONS", "INTERNATIONAL_BUSINESS"],
            "affected_entities_explanation": "Стосується підзвітних фінансових установ.",
            "practical_impact": "Потрібні оновлення процедур CRS onboarding і reporting.",
            "required_actions": ["Перевірити CRS due diligence, класифікацію рахунків і звітні файли."],
            "deadlines": [{"date": "2026-07-01", "description": "Початок застосування змін."}],
            "risks": [{"type": "reporting", "description": "Ризик некоректної CRS-звітності."}],
            "importance": "HIGH",
            "importance_reason": "Вимоги вже застосовуються для підзвітних фінансових установ.",
            "official_source_url": "https://www.mof.gov.ua/uk/crs-578",
            "missing_information": [],
            "confidence": 0.94,
        },
    },
]


def make_document(case: dict[str, Any]) -> Document:
    data = case["document"]
    return Document(
        id=data["id"],
        source_id=data["id"],
        identity_key=f"external_id:{data['external_id']}",
        identity_type="external_id",
        external_id=data["external_id"],
        canonical_url=data["canonical_url"],
        title=data["title"],
        document_type=data["document_type"],
    )


def make_version(document_id: int, version_id: int, content: str) -> DocumentVersion:
    return DocumentVersion(
        id=version_id,
        document_id=document_id,
        version_number=version_id,
        raw_content=content,
        normalized_content=content,
        content_hash=f"demo-{document_id}-{version_id}",
        version_metadata={"demo": True},
    )


async def run_case(case: dict[str, Any]) -> dict[str, Any]:
    provider = DemoProvider([case["relevance"], case["analysis"]])
    service = Stage2AnalysisService(
        relevance_service=AIRelevanceService(provider, "demo"),
        analysis_service=AIAnalysisService(provider, "demo"),
    )
    document = make_document(case)
    previous_version = make_version(document.id, 1, case["previous_text"])
    current_version = make_version(document.id, 2, case["current_text"])
    result = await service.process(
        status=ProcessingStatus.CHANGED,
        document=document,
        previous_version=previous_version,
        current_version=current_version,
        source_code=case["source_code"],
    )
    assert result is not None
    return {
        "case": case["name"],
        "stage2_status": result["status"],
        "diff_changed": result["diff"]["changed"],
        "diff_summary": result["diff"]["summary_stats"],
        "relevance": result["relevance"],
        "summary": result["analysis"]["summary"] if result["analysis"] else None,
        "importance": result["analysis"]["importance"] if result["analysis"] else None,
        "required_actions": result["analysis"]["required_actions"] if result["analysis"] else [],
        "usage": result["usage"],
        "provider_calls": [call["request_type"] for call in provider.calls],
    }


async def main() -> None:
    outputs = [await run_case(case) for case in CASES]
    print(json.dumps(outputs, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
