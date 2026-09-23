import asyncio
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.ai.stage2_service import create_stage2_service_from_settings
from app.models.document import Document
from app.models.document_version import DocumentVersion
from app.models.enums import ProcessingStatus


async def main() -> None:
    service = create_stage2_service_from_settings()
    if service is None:
        print("AI live smoke skipped: AI_API_KEY is not configured.")
        return

    document = Document(
        id=1,
        source_id=1,
        identity_key="smoke:crs-2",
        identity_type="external_id",
        external_id="1025759",
        canonical_url="https://tax.gov.ua/media-tsentr/novini/1025759.html",
        title="CRS 2.0: в Україні запроваджують нові правила звітності щодо фінансових рахунків",
        document_type="news",
    )
    version = DocumentVersion(
        id=1,
        document_id=1,
        version_number=1,
        raw_content="",
        normalized_content=(
            "З 1 липня 2026 року в Україні почнуть діяти оновлені вимоги "
            "міжнародного стандарту автоматичного обміну інформацією про фінансові "
            "рахунки CRS 2.0. Відповідні зміни затверджені наказом Міністерства "
            "фінансів України від 15 червня 2026 року № 316."
        ),
        content_hash="smoke",
        version_metadata={"official": True},
    )

    result = await service.process(
        status=ProcessingStatus.NEW,
        document=document,
        current_version=version,
        previous_version=None,
        source_code="dps",
    )
    concise = {
        "status": result.get("status") if result else None,
        "relevance": result.get("relevance") if result else None,
        "summary": (result.get("analysis") or {}).get("summary") if result else None,
        "importance": (result.get("analysis") or {}).get("importance") if result else None,
        "knowledge_base_article": (result.get("content") or {}).get("knowledge_base_article")
        if result
        else None,
        "telegram_post": (result.get("content") or {}).get("telegram_post") if result else None,
        "content_warnings": (result.get("content") or {}).get("content_warnings") if result else None,
        "usage": result.get("usage") if result else [],
    }
    print(json.dumps(concise, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
