from app.sources.base import NormalizedDocument, RawDocument, SourceAdapter
from app.utils.normalization import normalize_legal_text


class MockSourceAdapter(SourceAdapter):
    def __init__(self, source_code: str = "mock", documents: list[RawDocument] | None = None) -> None:
        self._source_code = source_code
        self.documents = documents or []

    @property
    def source_code(self) -> str:
        return self._source_code

    async def fetch_items(self) -> list[RawDocument]:
        return self.documents

    async def normalize(self, document: RawDocument) -> NormalizedDocument:
        if document.content is None:
            raise ValueError("Mock document content is required")
        return NormalizedDocument(
            source_code=self.source_code,
            external_id=document.external_id,
            canonical_url=document.canonical_url,
            title=document.title or "Untitled document",
            content=normalize_legal_text(document.content),
            document_type=document.document_type,
            published_at=document.published_at,
            effective_at=document.effective_at,
            metadata=document.metadata,
        )
