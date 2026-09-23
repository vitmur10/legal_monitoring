from sqlalchemy import select

from app.models.document_version import DocumentVersion
from app.models.enums import ProcessingStatus
from app.services.monitoring_service import MonitoringService
from app.sources.zir.adapter import ZirAdapter
from app.sources.zir.schemas import ZirStatus
from app.sources.registry import SourceRegistry
from tests.fixtures.builders import source


class VersionedZirClient:
    def __init__(self) -> None:
        self.answer = "Old answer"
        self.include_bad = False

    async def initialize_session(self) -> str:
        return "<html>search</html>"

    async def search_consultations(self, **kwargs) -> str:
        bad_row = """
        <div id="result_row" row-id="bad">
          <div id="title"><a href="/main/bz/view/?src=ques&amp;id=bad"><span>Bad item</span></a></div>
        </div>
        """ if self.include_bad else ""
        return _search_xml(
            f"""
            <div id="result_row" row-id="38043">
              <div id="title"><a href="/main/bz/view/?src=ques&amp;id=38043">
                <span>Які платники ЄП можуть бути платниками ПДВ?</span></a></div>
            </div>
            {bad_row}
            """,
            2 if self.include_bad else 1,
        )

    async def load_more(self, srch_words: str = "") -> str:
        return '<?xml version="1.0" encoding="UTF-8"?><body><content></content></body>'

    async def get_consultation_page(self, zir_id: str, src: str = "ques") -> str:
        if zir_id == "bad":
            raise ValueError("bad source response")
        return f"""
        <fieldset><legend>Питання</legend>Які платники ЄП можуть бути платниками ПДВ?</fieldset>
        <fieldset><legend>Відповідь</legend>Коротка:<br />Так.<br />Повна:<br />{self.answer} п. 180.1 ст. 180 ПКУ.</fieldset>
        """

    async def get_answer_content(self, zir_id: str, src: str = "ques", srch_words: str = "") -> str:
        return f"Коротка:<br />Так.<br />Повна:<br />{self.answer}"


async def test_zir_same_id_new_unchanged_changed(session_factory) -> None:
    async with session_factory() as session:
        db_source = source(code="zir")
        session.add(db_source)
        await session.commit()
        source_id = db_source.id

    client = VersionedZirClient()
    adapter = ZirAdapter(client=client, category_ids=["1"], statuses=[ZirStatus.CURRENT], max_load_more_batches=0)
    registry = SourceRegistry()
    registry.register(adapter)
    service = MonitoringService(session_factory, registry)

    first = await service.run_source(source_id)
    second = await service.run_source(source_id)
    client.answer = "New answer"
    third = await service.run_source(source_id)

    assert [result.status for result in first] == [ProcessingStatus.NEW]
    assert [result.status for result in second] == [ProcessingStatus.UNCHANGED]
    assert [result.status for result in third] == [ProcessingStatus.CHANGED]

    async with session_factory() as session:
        versions = (await session.execute(select(DocumentVersion).order_by(DocumentVersion.version_number))).scalars().all()
    assert [version.version_number for version in versions] == [1, 2]


async def test_zir_one_item_failure_does_not_break_monitoring_run(session_factory) -> None:
    async with session_factory() as session:
        db_source = source(code="zir")
        session.add(db_source)
        await session.commit()
        source_id = db_source.id

    client = VersionedZirClient()
    client.include_bad = True
    adapter = ZirAdapter(client=client, category_ids=["1"], max_load_more_batches=0)
    registry = SourceRegistry()
    registry.register(adapter)
    service = MonitoringService(session_factory, registry)

    results = await service.run_source(source_id)

    assert [result.status for result in results] == [ProcessingStatus.NEW, ProcessingStatus.FAILED]


def _search_xml(content_html: str, count: int) -> str:
    escaped = (
        content_html.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
    return f'<?xml version="1.0" encoding="UTF-8"?><body><count>{count}</count><content>{escaped}</content></body>'
