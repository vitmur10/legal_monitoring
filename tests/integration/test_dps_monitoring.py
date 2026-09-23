from app.models.enums import ProcessingStatus
from app.services.monitoring_service import MonitoringService
from app.sources.base import RawDocument
from app.sources.dps.adapter import DpsAdapter
from app.sources.registry import SourceRegistry
from tests.fixtures.builders import source


class FixedDpsAdapter(DpsAdapter):
    async def fetch_items(self) -> list[RawDocument]:
        return [
            RawDocument(
                source_code=self.source_code,
                external_id="dps:1025759",
                canonical_url="https://tax.gov.ua/media-tsentr/novini/1025759.html",
                title="CRS 2.0",
                content="Stable DPS content",
                document_type="NEWS",
            )
        ]

    async def fetch_document(self, item: RawDocument) -> RawDocument:
        return item


async def test_dps_adapter_output_is_compatible_with_monitoring_pipeline(session_factory):
    async with session_factory() as session:
        db_source = source(code="dps")
        session.add(db_source)
        await session.commit()
        source_id = db_source.id

    registry = SourceRegistry()
    registry.register(FixedDpsAdapter())
    service = MonitoringService(session_factory, registry)

    first = await service.run_source(source_id)
    second = await service.run_source(source_id)

    assert [item.status for item in first] == [ProcessingStatus.NEW]
    assert [item.status for item in second] == [ProcessingStatus.UNCHANGED]
