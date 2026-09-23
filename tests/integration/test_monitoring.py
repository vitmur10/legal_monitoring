from sqlalchemy import select

from app.models.enums import MonitoringRunStatus, ProcessingStatus
from app.models.monitoring_run import MonitoringRun
from app.models.source import Source
from app.services.monitoring_service import MonitoringService
from app.sources.base import RawDocument
from app.sources.mock import MockSourceAdapter
from app.sources.registry import SourceRegistry
from tests.fixtures.builders import raw_document, source


class FailingNormalizeAdapter(MockSourceAdapter):
    async def normalize(self, document: RawDocument):
        if document.external_id == "bad":
            raise ValueError("broken item")
        return await super().normalize(document)


async def test_adapter_error_does_not_stop_monitoring_and_counters_are_correct(session_factory):
    async with session_factory() as session:
        db_source = source()
        session.add(db_source)
        await session.commit()
        source_id = db_source.id

    adapter = FailingNormalizeAdapter(
        documents=[
            raw_document(external_id="good-new", content="A"),
            raw_document(external_id="bad", content="B"),
            raw_document(external_id="good-same", content="C"),
        ]
    )
    registry = SourceRegistry()
    registry.register(adapter)
    service = MonitoringService(session_factory, registry)

    await service.run_source(source_id)
    adapter.documents = [
        raw_document(external_id="good-new", content="A"),
        raw_document(external_id="bad", content="B"),
        raw_document(external_id="good-same", content="C"),
    ]
    results = await service.run_source(source_id)

    assert [result.status for result in results] == [
        ProcessingStatus.UNCHANGED,
        ProcessingStatus.FAILED,
        ProcessingStatus.UNCHANGED,
    ]

    async with session_factory() as session:
        runs = (await session.execute(select(MonitoringRun).order_by(MonitoringRun.id))).scalars().all()
    assert runs[-1].status == MonitoringRunStatus.COMPLETED
    assert runs[-1].items_found == 3
    assert runs[-1].new_count == 0
    assert runs[-1].changed_count == 0
    assert runs[-1].unchanged_count == 2
    assert runs[-1].failed_count == 1


async def test_disabled_source_is_not_scheduled(session_factory):
    from app.monitoring.scheduler import MonitoringScheduler

    async with session_factory() as session:
        session.add(source(code="mock", enabled=True))
        session.add(source(code="disabled_mock", enabled=False))
        await session.commit()

    registry = SourceRegistry()
    registry.register(MockSourceAdapter(source_code="mock"))
    registry.register(MockSourceAdapter(source_code="disabled_mock"))
    scheduler = MonitoringScheduler(session_factory, registry)
    await scheduler.start()
    jobs = scheduler.scheduler.get_jobs()
    scheduler.shutdown()

    assert len(jobs) == 1
    assert jobs[0].id == "source:1"
