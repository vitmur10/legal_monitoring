import asyncio

from sqlalchemy import select

from app.models.document import Document
from app.models.document_version import DocumentVersion
from app.models.enums import ProcessingStatus
from app.services.versioning_service import VersioningService
from app.sources.mock import MockSourceAdapter
from tests.fixtures.builders import raw_document, source


async def _create_source(session, code: str = "mock"):
    db_source = source(code=code)
    session.add(db_source)
    await session.commit()
    await session.refresh(db_source)
    return db_source


async def _process(session, db_source, raw):
    adapter = MockSourceAdapter(source_code=db_source.code, documents=[raw])
    normalized = await adapter.normalize(raw)
    result = await VersioningService().process_document(session, db_source, normalized, raw.content or "")
    await session.commit()
    return result


async def test_new_document_creates_version_1(session):
    db_source = await _create_source(session)
    result = await _process(session, db_source, raw_document())

    assert result.status == ProcessingStatus.NEW
    versions = (await session.execute(select(DocumentVersion))).scalars().all()
    assert len(versions) == 1
    assert versions[0].version_number == 1


async def test_same_content_is_unchanged_and_no_new_version(session):
    db_source = await _create_source(session)
    await _process(session, db_source, raw_document())
    result = await _process(session, db_source, raw_document())

    assert result.status == ProcessingStatus.UNCHANGED
    versions = (await session.execute(select(DocumentVersion))).scalars().all()
    assert len(versions) == 1


async def test_changed_content_creates_version_2(session):
    db_source = await _create_source(session)
    await _process(session, db_source, raw_document(content="Old legal rule"))
    result = await _process(session, db_source, raw_document(content="New legal rule"))

    assert result.status == ProcessingStatus.CHANGED
    versions = (await session.execute(select(DocumentVersion).order_by(DocumentVersion.version_number))).scalars().all()
    assert [version.version_number for version in versions] == [1, 2]


async def test_same_external_id_does_not_create_duplicate_document(session):
    db_source = await _create_source(session)
    await _process(session, db_source, raw_document(content="Old legal rule"))
    await _process(session, db_source, raw_document(content="New legal rule"))

    documents = (await session.execute(select(Document))).scalars().all()
    assert len(documents) == 1


async def test_concurrent_duplicate_version_scenario_does_not_corrupt_data(file_session_factory):
    async with file_session_factory() as setup:
        db_source = await _create_source(setup)
        source_id = db_source.id

    async def worker():
        async with file_session_factory() as session:
            db_source = await session.get(type(source()), source_id)
            return await _process(session, db_source, raw_document(content="Old legal rule"))

    results = await asyncio.gather(worker(), worker())
    statuses = sorted(result.status for result in results)

    async with file_session_factory() as session:
        documents = (await session.execute(select(Document))).scalars().all()
        versions = (await session.execute(select(DocumentVersion))).scalars().all()

    assert statuses == [ProcessingStatus.NEW, ProcessingStatus.UNCHANGED]
    assert len(documents) == 1
    assert len(versions) == 1
