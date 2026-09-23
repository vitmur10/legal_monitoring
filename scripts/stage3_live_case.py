import asyncio
import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.session import AsyncSessionLocal
from app.ai.stage2_service import create_stage2_service_from_settings
from app.models.enums import ProcessingStatus
from app.models.source import Source
from app.repositories.document_repository import DocumentRepository
from app.services.versioning_service import VersioningService
from app.sources.base import NormalizedDocument
from app.stage3.factory import create_review_service


async def main(run_id: str | None = None) -> None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Source).where(Source.code == "dps"))
        source = result.scalar_one_or_none()
        if source is None:
            source = Source(
                code="dps",
                name="State Tax Service of Ukraine",
                base_url="https://tax.gov.ua",
                enabled=False,
                check_interval_minutes=60,
            )
            session.add(source)
            await session.flush()

        external_id = f"1025759-{run_id}" if run_id else "1025759"
        canonical_url = "https://tax.gov.ua/media-tsentr/novini/1025759.html"
        if run_id:
            canonical_url = f"{canonical_url}#stage3-{run_id}"
        normalized = NormalizedDocument(
            source_code="dps",
            external_id=external_id,
            canonical_url=canonical_url,
            title=(
                f"{'[Фінальний тест] ' if run_id else ''}"
                "CRS 2.0: нові правила звітності щодо фінансових рахунків"
            ),
            content=(
                "Наказом Міністерства фінансів України від 15 червня 2026 року № 316 "
                "оновлено порядок застосування CRS з урахуванням CRS 2.0. Зміни "
                "охоплюють електронні гроші, цифрові валюти центральних банків (CBDC) "
                "та віртуальні активи й застосовуються з 1 липня 2026 року. Вони "
                "безпосередньо стосуються підзвітних фінансових установ в Україні, "
                "яким потрібно переглянути процедури CRS due diligence, класифікацію "
                "фінансових рахунків та формування звітних файлів."
            ),
            document_type="news",
            published_at=datetime.now(timezone.utc),
            metadata={"official": True, "demo": "stage3_live_acceptance"},
        )
        processing = await VersioningService().process_document(
            session,
            source,
            normalized,
            raw_content=normalized.content,
        )
        await session.commit()

        version_id = processing.current_version_id
        if version_id is None:
            raise RuntimeError("The test document has no current version")
        version = await DocumentRepository(session).get_version(version_id)
        if ((version.version_metadata or {}).get("stage2") or {}).get("status") != "ANALYZED":
            stage2_service = create_stage2_service_from_settings()
            if stage2_service is None:
                raise RuntimeError("AI Stage 2 is not configured")
            document = await DocumentRepository(session).get(processing.document_id)
            stage2 = await stage2_service.process(
                status=ProcessingStatus.NEW,
                document=document,
                current_version=version,
                previous_version=None,
                source_code="dps",
            )
            metadata = dict(version.version_metadata or {})
            metadata["stage2"] = stage2
            version.version_metadata = metadata
            await session.commit()
        stage3 = (version.version_metadata or {}).get("stage3") or {}
        if not stage3.get("moderation_messages"):
            await create_review_service(session).dispatch_to_moderation(version_id)
            await session.commit()

        print(f"processing_status={processing.status.value}")
        print(f"document_id={processing.document_id}")
        print(f"version_id={version_id}")
        print("moderation_status=SENT")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id")
    args = parser.parse_args()
    asyncio.run(main(args.run_id))
