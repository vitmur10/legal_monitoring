from app.models.source import Source
from app.sources.base import RawDocument


def source(code: str = "mock", enabled: bool = True) -> Source:
    return Source(
        code=code,
        name=f"{code} source",
        base_url="https://example.test",
        enabled=enabled,
        check_interval_minutes=60,
    )


def raw_document(
    external_id: str = "law-001",
    content: str = "Old legal rule",
    title: str = "Document A",
    source_code: str = "mock",
) -> RawDocument:
    return RawDocument(
        source_code=source_code,
        external_id=external_id,
        canonical_url=f"https://example.test/{external_id}",
        title=title,
        content=content,
        document_type="law",
    )
