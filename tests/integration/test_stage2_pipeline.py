from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.models.document_version import DocumentVersion
from app.models.enums import ProcessingStatus
from app.services.versioning_service import VersioningService
from app.sources.base import NormalizedDocument
from tests.fixtures.builders import source


class FakeStage2Service:
    def __init__(self, result_status: str = "ANALYZED", fail: bool = False) -> None:
        self.calls: list[dict[str, Any]] = []
        self.result_status = result_status
        self.fail = fail

    async def process(self, **kwargs) -> dict[str, Any]:
        self.calls.append(kwargs)
        if self.fail:
            return {
                "status": "AI_FAILED",
                "error": "provider unavailable",
                "usage": [],
                "diff": None,
                "relevance": None,
                "analysis": None,
            }
        return {
            "status": self.result_status,
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
            "relevance": {
                "relevant": self.result_status != "FILTERED_OUT",
                "categories": ["VAT"] if self.result_status != "FILTERED_OUT" else [],
                "reason": "test",
                "confidence": 0.9,
            },
            "analysis": {"summary": "test"} if self.result_status == "ANALYZED" else None,
            "usage": [{"model": "mock", "request_type": "relevance", "total_tokens": 10}],
        }


def normalized(content: str, external_id: str = "doc-1") -> NormalizedDocument:
    return NormalizedDocument(
        source_code="mock",
        external_id=external_id,
        canonical_url=f"https://example.test/{external_id}",
        title="Tax document",
        document_type="law",
        content=content,
        metadata={"source_metadata": True},
    )


async def test_new_document_runs_stage2_and_persists_metadata(session) -> None:
    src = source()
    session.add(src)
    await session.flush()
    fake = FakeStage2Service()
    service = VersioningService(stage2_service=fake)

    result = await service.process_document(session, src, normalized("new tax rule"), "raw")

    assert result.status == ProcessingStatus.NEW
    assert len(fake.calls) == 1
    version = await session.get(DocumentVersion, result.current_version_id)
    assert version is not None
    assert version.version_metadata["source_metadata"] is True
    assert version.version_metadata["stage2"]["status"] == "ANALYZED"


async def test_unchanged_document_skips_stage2(session) -> None:
    src = source()
    session.add(src)
    await session.flush()
    fake = FakeStage2Service()
    service = VersioningService(stage2_service=fake)

    await service.process_document(session, src, normalized("same content"), "raw")
    result = await service.process_document(session, src, normalized("same content"), "raw")

    assert result.status == ProcessingStatus.UNCHANGED
    assert len(fake.calls) == 1


async def test_changed_document_runs_stage2_with_previous_version(session) -> None:
    src = source()
    session.add(src)
    await session.flush()
    fake = FakeStage2Service()
    service = VersioningService(stage2_service=fake)

    first = await service.process_document(session, src, normalized("old tax rule"), "raw")
    second = await service.process_document(session, src, normalized("new tax rule"), "raw")

    assert second.status == ProcessingStatus.CHANGED
    assert len(fake.calls) == 2
    assert fake.calls[-1]["previous_version"].id == first.current_version_id
    version = await session.get(DocumentVersion, second.current_version_id)
    assert version.version_metadata["stage2"]["status"] == "ANALYZED"


async def test_filtered_out_metadata_is_persisted(session) -> None:
    src = source()
    session.add(src)
    await session.flush()
    fake = FakeStage2Service(result_status="FILTERED_OUT")
    service = VersioningService(stage2_service=fake)

    result = await service.process_document(session, src, normalized("conference news"), "raw")

    version = await session.get(DocumentVersion, result.current_version_id)
    assert version.version_metadata["stage2"]["status"] == "FILTERED_OUT"
    assert version.version_metadata["stage2"]["relevance"]["relevant"] is False


async def test_stage2_failure_does_not_corrupt_versioning(session) -> None:
    src = source()
    session.add(src)
    await session.flush()
    fake = FakeStage2Service(fail=True)
    service = VersioningService(stage2_service=fake)

    result = await service.process_document(session, src, normalized("tax rule"), "raw")
    versions = (
        await session.execute(select(DocumentVersion).where(DocumentVersion.document_id == result.document_id))
    ).scalars().all()

    assert result.status == ProcessingStatus.NEW
    assert len(versions) == 1
    assert versions[0].version_metadata["stage2"]["status"] == "AI_FAILED"
