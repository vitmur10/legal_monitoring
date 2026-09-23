import asyncio
from uuid import uuid4

from sqlalchemy import select

from app.db.session import AsyncSessionLocal, engine
from app.models.enums import ProcessingStatus
from app.models.source import Source
from app.services.monitoring_service import MonitoringService
from app.sources.base import RawDocument
from app.sources.mock import MockSourceAdapter
from app.sources.registry import SourceRegistry


SOURCE_CODE = "mock"


async def ensure_source() -> Source:
    async with AsyncSessionLocal() as session:
        source = (
            await session.execute(select(Source).where(Source.code == SOURCE_CODE))
        ).scalar_one_or_none()
        if source is None:
            source = Source(
                code=SOURCE_CODE,
                name="Versioning acceptance demo",
                base_url="https://example.test",
            )
            session.add(source)
            await session.commit()
            await session.refresh(source)
        return source


def controlled_document(external_id: str, content: str) -> RawDocument:
    return RawDocument(
        source_code=SOURCE_CODE,
        external_id=external_id,
        canonical_url=f"https://example.test/{external_id}",
        title="Stage 1 versioning acceptance document",
        content=content,
        document_type="acceptance_demo",
    )


def print_result(run_number: int, description: str, result) -> None:
    print(f"RUN {run_number} - {description}")
    print(f"  status              = {result.status.value}")
    print(f"  previous_version_id = {result.previous_version_id}")
    print(f"  current_version_id  = {result.current_version_id}")
    print()


def verify(first, second, third) -> None:
    assert first.status == ProcessingStatus.NEW
    assert first.previous_version_id is None
    assert first.current_version_id is not None

    assert second.status == ProcessingStatus.UNCHANGED
    assert second.previous_version_id == first.current_version_id
    assert second.current_version_id == first.current_version_id

    assert third.status == ProcessingStatus.CHANGED
    assert third.previous_version_id == first.current_version_id
    assert third.current_version_id is not None
    assert third.current_version_id != first.current_version_id


async def main() -> None:
    external_id = f"stage1-versioning-{uuid4().hex}"
    source = await ensure_source()

    adapter = MockSourceAdapter(source_code=SOURCE_CODE)
    registry = SourceRegistry()
    registry.register(adapter)
    service = MonitoringService(AsyncSessionLocal, registry)

    print("=" * 58)
    print("STAGE 1 VERSIONING - ACCEPTANCE DEMO")
    print("=" * 58)
    print(f"Controlled document: {external_id}")
    print()

    adapter.documents = [
        controlled_document(
            external_id,
            "Controlled rule: the report is submitted monthly.",
        )
    ]
    first = (await service.run_source(source.id))[0]
    print_result(1, "initial meaningful content", first)

    adapter.documents = [
        controlled_document(
            external_id,
            "  Controlled   rule: the report is submitted monthly.  ",
        )
    ]
    second = (await service.run_source(source.id))[0]
    print_result(2, "same meaningful content", second)

    adapter.documents = [
        controlled_document(
            external_id,
            "Controlled rule: the report is submitted quarterly.",
        )
    ]
    third = (await service.run_source(source.id))[0]
    print_result(3, "changed meaningful content", third)

    verify(first, second, third)
    print("RESULT: PASS")
    print("NEW -> UNCHANGED -> CHANGED confirmed")
    print("=" * 58)


async def run() -> None:
    try:
        await main()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run())
