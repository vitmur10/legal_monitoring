import asyncio

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.db.base import Base
from app.models.document import Document
from app.models.document_relation import DocumentRelation
from app.models.enums import RelationType
from app.models.source import Source
from app.services.monitoring_service import MonitoringService
from app.sources.base import RawDocument
from app.sources.rada.adapter import RadaAdapter
from app.sources.registry import SourceRegistry
from app.utils.hashing import sha256_text


class FixedRadaAdapter(RadaAdapter):
    async def fetch_items(self) -> list[RawDocument]:
        return [
            RawDocument(source_code=self.source_code, external_id="2755-17"),
            RawDocument(source_code=self.source_code, external_id="4835-20"),
        ]


async def main() -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    db_backend = "postgresql"
    try:
        async with engine.connect() as conn:
            await conn.execute(text("select 1"))
            tables = (
                await conn.execute(
                    text(
                        "select table_name from information_schema.tables "
                        "where table_schema = 'public' order by table_name"
                    )
                )
            ).scalars().all()
        print("postgresql_available=true")
        print("tables=" + ",".join(tables))
    except Exception as exc:
        await engine.dispose()
        print("postgresql_available=false")
        print("postgresql_error=" + exc.__class__.__name__ + ": " + str(exc))
        db_backend = "sqlite_fallback"
        engine = create_async_engine("sqlite+aiosqlite:///./rada_e2e.sqlite")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    print("db_backend=" + db_backend)

    async with session_factory() as session:
        result = await session.execute(select(Source).where(Source.code == "rada"))
        source = result.scalar_one_or_none()
        if source is None:
            source = Source(
                code="rada",
                name="Verkhovna Rada of Ukraine",
                base_url="https://zakon.rada.gov.ua",
                enabled=True,
                check_interval_minutes=1440,
            )
            session.add(source)
            await session.commit()
            await session.refresh(source)
        source_id = source.id

    registry = SourceRegistry()
    registry.register(FixedRadaAdapter())
    service = MonitoringService(session_factory, registry)

    first = await service.run_source(source_id)
    second = await service.run_source(source_id)
    print("first=" + ",".join(f"{item.external_id}:{item.status.value}" for item in first))
    print("second=" + ",".join(f"{item.external_id}:{item.status.value}" for item in second))

    async with session_factory() as session:
        docs = (
            await session.execute(
                select(Document).where(Document.source_id == source_id).order_by(Document.external_id)
            )
        ).scalars().all()
        doc_by_external_id = {doc.external_id: doc for doc in docs}
        relations = (
            await session.execute(
                select(DocumentRelation)
                .where(
                    DocumentRelation.from_document_id
                    == doc_by_external_id["4835-20"].id
                )
                .where(
                    DocumentRelation.to_document_id
                    == doc_by_external_id["2755-17"].id
                )
                .where(DocumentRelation.relation_type == RelationType.AMENDS)
            )
        ).scalars().all()
        print("documents=" + ",".join(f"{doc.external_id}:{doc.id}" for doc in docs))
        print("relation_count=" + str(len(relations)))
        for relation in relations:
            print("relation_metadata=" + repr(relation.relation_metadata))

    adapter = RadaAdapter()
    revisions = {}
    for revision in ("2026-01-01", "2026-04-15"):
        raw = await adapter.fetch_by_nreg("2755-17", revision)
        normalized = await adapter.normalize(raw)
        revisions[revision] = sha256_text(normalized.content)
        print(
            "revision={revision} len={length} revision_date={revision_date} "
            "basis={basis} hash={content_hash}".format(
                revision=revision,
                length=len(normalized.content),
                revision_date=normalized.metadata.get("revision_date"),
                basis=normalized.metadata.get("specific_revision_basis_nregs"),
                content_hash=revisions[revision],
            )
        )
    print("revision_hashes_differ=" + str(revisions["2026-01-01"] != revisions["2026-04-15"]))
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
