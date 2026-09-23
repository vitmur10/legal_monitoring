import asyncio
from pathlib import Path
import sys

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.session import AsyncSessionLocal
from app.models.source import Source
from app.services.versioning_service import VersioningService
from app.sources.base import NormalizedDocument


CASES = [
    {
        "source_code": "rada",
        "source_name": "Verkhovna Rada of Ukraine",
        "base_url": "https://rada.gov.ua",
        "document": NormalizedDocument(
            source_code="rada",
            external_id="4835-IX-stage3-clean",
            canonical_url="https://zakon.rada.gov.ua/laws/show/4835-20#Text",
            title="[Тест: виправлення] Закон України №4835-IX",
            document_type="law",
            content=(
                "Пункт 16-1 підрозділу 10 розділу XX Податкового кодексу України: "
                "військовий збір застосовується до 31 грудня третього календарного "
                "року, наступного за роком припинення або скасування воєнного стану. "
                "Закон прийнято 7 квітня 2026 року, набрання чинності — 15 квітня "
                "2026 року. Зміна стосується роботодавців, податкових агентів та "
                "платників податків."
            ),
            metadata={"demo": "stage3_revision_acceptance", "official": True},
        ),
    },
    {
        "source_code": "rada",
        "source_name": "Verkhovna Rada of Ukraine",
        "base_url": "https://rada.gov.ua",
        "document": NormalizedDocument(
            source_code="rada",
            external_id="4835-IX-stage3-rejection",
            canonical_url="https://zakon.rada.gov.ua/laws/show/4835-20#stage3-rejection",
            title="[Тест: відхилення] Закон України №4835-IX",
            document_type="law",
            content=(
                "Пункт 16-1 підрозділу 10 розділу XX Податкового кодексу України: "
                "військовий збір застосовується до 31 грудня третього календарного "
                "року, наступного за роком припинення або скасування воєнного стану. "
                "Закон прийнято 7 квітня 2026 року, набрання чинності — 15 квітня "
                "2026 року. Зміна стосується роботодавців, податкових агентів та "
                "платників податків."
            ),
            metadata={"demo": "stage3_rejection_acceptance", "official": True},
        ),
    },
]


async def source_for(session, case: dict) -> Source:
    result = await session.execute(select(Source).where(Source.code == case["source_code"]))
    source = result.scalar_one_or_none()
    if source is not None:
        return source
    source = Source(
        code=case["source_code"],
        name=case["source_name"],
        base_url=case["base_url"],
        enabled=False,
        check_interval_minutes=60,
    )
    session.add(source)
    await session.flush()
    return source


async def main() -> None:
    async with AsyncSessionLocal() as session:
        for case in CASES:
            source = await source_for(session, case)
            document = case["document"]
            result = await VersioningService().process_document(
                session,
                source,
                document,
                raw_content=document.content,
            )
            await session.commit()
            print(
                f"sent title={document.title!r} status={result.status.value} "
                f"document_id={result.document_id} version_id={result.current_version_id}"
            )


if __name__ == "__main__":
    asyncio.run(main())
