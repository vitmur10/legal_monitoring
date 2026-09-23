import asyncio
import os

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.models.document import Document
from app.models.document_version import DocumentVersion
from app.models.enums import ProcessingStatus
from app.services.versioning_service import VersioningService
from app.sources.mock import MockSourceAdapter
from tests.fixtures.builders import raw_document, source


pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="PostgreSQL-specific checks require TEST_DATABASE_URL",
)


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


async def test_postgresql_allows_multiple_null_external_id_and_uses_url_identity(session):
    db_source = await _create_source(session)

    first = raw_document(external_id=None, title="First", content="A")
    first.canonical_url = "https://example.test/first"
    second = raw_document(external_id=None, title="Second", content="B")
    second.canonical_url = "https://example.test/second"

    first_result = await _process(session, db_source, first)
    second_result = await _process(session, db_source, second)

    assert first_result.status == ProcessingStatus.NEW
    assert second_result.status == ProcessingStatus.NEW
    count = await session.scalar(select(func.count()).select_from(Document))
    assert count == 2


async def test_postgresql_allows_multiple_null_canonical_url_and_uses_external_id(session):
    db_source = await _create_source(session)

    first = raw_document(external_id="null-url-1", title="First", content="A")
    first.canonical_url = None
    second = raw_document(external_id="null-url-2", title="Second", content="B")
    second.canonical_url = None

    await _process(session, db_source, first)
    await _process(session, db_source, second)

    count = await session.scalar(select(func.count()).select_from(Document))
    assert count == 2


async def test_postgresql_content_hash_uniqueness_is_enforced(session):
    db_source = await _create_source(session)
    result = await _process(session, db_source, raw_document(content="A"))
    version = await session.get(DocumentVersion, result.current_version_id)

    duplicate = DocumentVersion(
        document_id=result.document_id,
        version_number=2,
        raw_content="A",
        normalized_content="A",
        content_hash=version.content_hash,
        version_metadata={},
        detected_at=version.detected_at,
    )
    session.add(duplicate)

    with pytest.raises(IntegrityError):
        await session.commit()


async def test_postgresql_identity_constraints_are_enforced(session):
    db_source = await _create_source(session)
    await _process(session, db_source, raw_document(external_id="same", content="A"))

    duplicate = Document(
        source_id=db_source.id,
        identity_key="external_id:same",
        identity_type="external_id",
        external_id="same",
        canonical_url="https://example.test/other",
        title="Duplicate",
        first_seen_at=await session.scalar(select(func.now())),
        last_seen_at=await session.scalar(select(func.now())),
    )
    session.add(duplicate)

    with pytest.raises(IntegrityError):
        await session.commit()


async def test_postgresql_concurrent_same_changed_version_creates_one_version(file_session_factory):
    async with file_session_factory() as setup:
        db_source = await _create_source(setup)
        source_id = db_source.id
        await _process(setup, db_source, raw_document(content="Version 1"))

    async def worker():
        async with file_session_factory() as session:
            db_source = await session.get(type(source()), source_id)
            return await _process(session, db_source, raw_document(content="Version 2"))

    results = await asyncio.gather(worker(), worker())

    async with file_session_factory() as session:
        versions = (
            await session.execute(
                select(DocumentVersion).order_by(DocumentVersion.version_number)
            )
        ).scalars().all()
        document = (await session.execute(select(Document))).scalar_one()

    assert sorted(result.status for result in results) == [
        ProcessingStatus.CHANGED,
        ProcessingStatus.UNCHANGED,
    ]
    assert [version.version_number for version in versions] == [1, 2]
    assert document.current_version_id == versions[-1].id
