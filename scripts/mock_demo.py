import asyncio

from sqlalchemy import select

from app.db.base import Base
from app.db.session import AsyncSessionLocal, engine
from app.models.document import Document
from app.models.document_version import DocumentVersion
from app.models.enums import RelationType
from app.models.source import Source
from app.repositories.relation_repository import DocumentRelationRepository
from app.services.monitoring_service import MonitoringService
from app.sources.base import RawDocument
from app.sources.mock import MockSourceAdapter
from app.sources.registry import SourceRegistry


async def ensure_mock_source() -> Source:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Source).where(Source.code == "mock"))
        source = result.scalar_one_or_none()
        if source is None:
            source = Source(code="mock", name="Mock source", base_url="https://example.test")
            session.add(source)
            await session.commit()
            await session.refresh(source)
        return source


async def run_monitoring_sequence(source: Source) -> None:
    registry = SourceRegistry()
    adapter = MockSourceAdapter(
        documents=[
            RawDocument(
                source_code="mock",
                external_id="law-001",
                canonical_url="https://example.test/law-001",
                title="Document A",
                content="Old legal rule",
                document_type="law",
            )
        ]
    )
    registry.register(adapter)
    service = MonitoringService(AsyncSessionLocal, registry)

    for label, content in [("RUN #1", "Old legal rule"), ("RUN #2", "Old legal rule"), ("RUN #3", "New legal rule")]:
        adapter.documents[0].content = content
        result = (await service.run_source(source.id))[0]
        print(f"{label}: {result.status} document_id={result.document_id} version_id={result.current_version_id}")


async def run_relation_sequence(source: Source) -> None:
    registry = SourceRegistry()
    adapter = MockSourceAdapter(
        documents=[
            RawDocument(source_code="mock", external_id="order-249", title="Minfin Order #249", content="Order 249"),
            RawDocument(source_code="mock", external_id="order-293", title="Minfin Order #293", content="Order 293"),
            RawDocument(
                source_code="mock",
                external_id="letter-15504",
                title="Tax Authority explanation",
                content="Explanation",
            ),
        ]
    )
    registry.register(adapter)
    await MonitoringService(AsyncSessionLocal, registry).run_source(source.id)

    async with AsyncSessionLocal() as session:
        docs = (
            await session.execute(select(Document).where(Document.source_id == source.id))
        ).scalars().all()
        by_external_id = {doc.external_id: doc for doc in docs}
        repo = DocumentRelationRepository(session)
        await repo.create(by_external_id["order-293"].id, by_external_id["order-249"].id, RelationType.AMENDS)
        await repo.create(by_external_id["letter-15504"].id, by_external_id["order-293"].id, RelationType.EXPLAINS)
        await session.commit()
        chain = await repo.fetch_chain(by_external_id["order-249"].id)
        print("Relation chain:")
        for relation in chain:
            print(f"{relation.from_document_id} {relation.relation_type} {relation.to_document_id}")


async def main() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    source = await ensure_mock_source()
    await run_monitoring_sequence(source)
    await run_relation_sequence(source)


if __name__ == "__main__":
    asyncio.run(main())
