import httpx
from sqlalchemy import select

from app.models.document import Document
from app.models.enums import MonitoringRunStatus, ProcessingStatus
from app.models.monitoring_run import MonitoringRun
from app.services.monitoring_service import MonitoringService
from app.sources.base import RawDocument
from app.sources.minfin.adapter import MinfinAdapter
from app.sources.minfin.client import MinfinClient
from app.sources.registry import SourceRegistry
from tests.fixtures.builders import source


class StaticMinfinAdapter(MinfinAdapter):
    def __init__(self, documents: list[RawDocument]) -> None:
        super().__init__(client=MinfinClient(min_delay=0), sections=[])
        self.documents = documents

    async def fetch_items(self) -> list[RawDocument]:
        return self.documents


class FailingMinfinAdapter(StaticMinfinAdapter):
    async def normalize(self, document: RawDocument):
        if document.external_id == "bad":
            raise ValueError("broken minfin item")
        return await super().normalize(document)


def _crs_raw(content: str) -> RawDocument:
    return RawDocument(
        source_code="minfin",
        external_id="page:578",
        canonical_url="https://mof.gov.ua/uk/crs-578",
        title="CRS: автоматичний обмін інформацією про фінансові рахунки",
        content=content,
        document_type="CRS",
        metadata={"attachments": [], "references": []},
    )


async def test_minfin_monitoring_new_unchanged_changed(session_factory) -> None:
    async with session_factory() as session:
        db_source = source(code="minfin")
        session.add(db_source)
        await session.commit()
        source_id = db_source.id

    adapter = StaticMinfinAdapter([_crs_raw("Title: CRS\nV1 initial content")])
    registry = SourceRegistry()
    registry.register(adapter)
    service = MonitoringService(session_factory, registry)

    first = await service.run_source(source_id)
    second = await service.run_source(source_id)
    adapter.documents = [_crs_raw("Title: CRS\nV2 changed meaningful CRS content")]
    third = await service.run_source(source_id)

    assert [result.status for result in first] == [ProcessingStatus.NEW]
    assert [result.status for result in second] == [ProcessingStatus.UNCHANGED]
    assert [result.status for result in third] == [ProcessingStatus.CHANGED]


async def test_minfin_access_blocked_discovery_creates_no_fake_document(session_factory) -> None:
    async with session_factory() as session:
        db_source = source(code="minfin")
        session.add(db_source)
        await session.commit()
        source_id = db_source.id

    client = MinfinClient(
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(403, request=request))
        ),
        retries=0,
        min_delay=0,
    )
    adapter = MinfinAdapter(client=client, sections=["https://mof.gov.ua/uk/crs-578"])
    registry = SourceRegistry()
    registry.register(adapter)
    service = MonitoringService(session_factory, registry)

    results = await service.run_source(source_id)

    assert results == []
    assert adapter.access_failures[0]["classification"] == "ACCESS_BLOCKED"
    async with session_factory() as session:
        documents = (await session.execute(select(Document))).scalars().all()
        runs = (await session.execute(select(MonitoringRun))).scalars().all()
    assert documents == []
    assert runs[-1].status == MonitoringRunStatus.COMPLETED
    assert runs[-1].items_found == 0


async def test_minfin_one_item_failure_does_not_break_monitoring_run(session_factory) -> None:
    async with session_factory() as session:
        db_source = source(code="minfin")
        session.add(db_source)
        await session.commit()
        source_id = db_source.id

    adapter = FailingMinfinAdapter(
        [
            _crs_raw("A"),
            RawDocument(source_code="minfin", external_id="bad", title="Bad", content="B"),
            RawDocument(
                source_code="minfin",
                external_id="order:2026-06-15:316",
                canonical_url="https://mof.gov.ua/uk/orders#order:2026-06-15:316",
                title="Наказ Мінфіну №316",
                content="Наказ Мінфіну №316",
                document_type="ORDER",
            ),
        ]
    )
    registry = SourceRegistry()
    registry.register(adapter)
    service = MonitoringService(session_factory, registry)

    results = await service.run_source(source_id)

    assert [result.status for result in results] == [
        ProcessingStatus.NEW,
        ProcessingStatus.FAILED,
        ProcessingStatus.NEW,
    ]
    async with session_factory() as session:
        runs = (await session.execute(select(MonitoringRun))).scalars().all()
    assert runs[-1].status == MonitoringRunStatus.COMPLETED
    assert runs[-1].failed_count == 1
