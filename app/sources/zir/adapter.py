from __future__ import annotations

from app.sources.base import NormalizedDocument, RawDocument, SourceAdapter
from app.sources.zir.client import ZirClient
from app.sources.zir.parser import (
    canonical_url,
    external_id,
    parse_answer_fragment,
    parse_category_path,
    parse_consultation_page,
    parse_external_id,
    parse_load_more_response,
    parse_search_response,
    semantic_content,
)
from app.sources.zir.schemas import ZirConsultationStub, ZirStatus
from app.utils.normalization import normalize_legal_text

DEFAULT_CATEGORY_ALLOWLIST = ["1", "62", "102", "181"]
STATUS_TO_SOURCE = {
    ZirStatus.CURRENT: "1",
    ZirStatus.NON_CURRENT: "2",
}


class ZirAdapter(SourceAdapter):
    def __init__(
        self,
        client: ZirClient | None = None,
        category_ids: list[str] | None = None,
        statuses: list[ZirStatus] | None = None,
        max_load_more_batches: int = 1,
        discovery_limit: int | None = 50,
        theme: str = "all",
        date_s: str = "",
        date_e: str = "",
    ) -> None:
        self.client = client or ZirClient()
        self.category_ids = category_ids or DEFAULT_CATEGORY_ALLOWLIST
        self.statuses = statuses or [ZirStatus.CURRENT]
        self.max_load_more_batches = max(0, max_load_more_batches)
        self.discovery_limit = discovery_limit
        self.theme = theme
        self.date_s = date_s
        self.date_e = date_e

    @property
    def source_code(self) -> str:
        return "zir"

    async def fetch_items(self) -> list[RawDocument]:
        await self.client.initialize_session()
        stubs: list[ZirConsultationStub] = []
        seen: set[str] = set()
        for category_id in self.category_ids:
            for status in self.statuses:
                response = await self.client.search_consultations(
                    cat_id=category_id,
                    status=STATUS_TO_SOURCE.get(status, "all"),
                    theme=self.theme,
                    date_s=self.date_s,
                    date_e=self.date_e,
                )
                search = parse_search_response(response, default_status=status)
                self._add_stubs(stubs, seen, search.items)
                for _batch in range(self.max_load_more_batches):
                    more_response = await self.client.load_more("")
                    more = parse_load_more_response(more_response, default_status=status)
                    if not more.items:
                        break
                    added = self._add_stubs(stubs, seen, more.items)
                    if added == 0:
                        break
                if self.discovery_limit is not None and len(stubs) >= self.discovery_limit:
                    return [self._stub_to_raw(stub) for stub in stubs[: self.discovery_limit]]
        return [self._stub_to_raw(stub) for stub in stubs]

    async def fetch_document(self, item: RawDocument) -> RawDocument:
        src, zir_id = self._identity_from_item(item)
        page_html = await self.client.get_consultation_page(zir_id, src)
        stub = self._stub_from_raw(item)
        consultation = parse_consultation_page(page_html, canonical_url(src, zir_id), fallback_stub=stub)

        if not consultation.short_answer and not consultation.full_answer:
            answer_html = await self.client.get_answer_content(zir_id, src)
            answer = parse_answer_fragment(answer_html)
            consultation.short_answer = answer.short_answer
            consultation.full_answer = answer.full_answer
            consultation.comments = consultation.comments or answer.comments
        if not consultation.short_answer and not consultation.full_answer:
            raise ValueError(f"ZIR consultation {zir_id} is missing answer")

        content = semantic_content(consultation)
        metadata = dict(item.metadata)
        metadata.update(
            {
                "src": consultation.src,
                "zir_id": consultation.id,
                "category": consultation.category,
                "status": consultation.status.value,
                "status_text": consultation.status_text,
                "short_answer": consultation.short_answer,
                "full_answer": consultation.full_answer,
                "comments": consultation.comments,
                "normative_references": [
                    reference.model_dump(mode="json")
                    for reference in consultation.normative_references
                ],
            }
        )
        return RawDocument(
            source_code=self.source_code,
            external_id=consultation.external_id,
            canonical_url=consultation.canonical_url,
            title=consultation.question,
            content=content,
            document_type="ZIR_CONSULTATION",
            metadata=metadata,
        )

    async def normalize(self, document: RawDocument) -> NormalizedDocument:
        if document.content is None:
            raise ValueError("ZIR document content is required")
        if not document.external_id:
            raise ValueError("ZIR document external_id is required")
        if not document.title:
            raise ValueError("ZIR document title is required")

        return NormalizedDocument(
            source_code=self.source_code,
            external_id=document.external_id,
            canonical_url=document.canonical_url,
            title=normalize_legal_text(document.title),
            content=normalize_legal_text(document.content),
            document_type=document.document_type,
            published_at=document.published_at,
            effective_at=document.effective_at,
            metadata=document.metadata,
        )

    async def fetch_by_id(self, zir_id: str, src: str = "ques") -> RawDocument:
        return await self.fetch_document(
            RawDocument(
                source_code=self.source_code,
                external_id=external_id(src, zir_id),
                canonical_url=canonical_url(src, zir_id),
                metadata={"src": src, "zir_id": zir_id},
            )
        )

    async def fetch_categories(self) -> list:
        await self.client.initialize_session()
        categories = []
        seen: set[str] = set()
        for category_id in self.category_ids:
            html = await self.client.get_category_path(category_id)
            for category in parse_category_path(html, parent_id=category_id):
                if category.id in seen:
                    continue
                seen.add(category.id)
                categories.append(category)
        return categories

    def _stub_to_raw(self, stub: ZirConsultationStub) -> RawDocument:
        return RawDocument(
            source_code=self.source_code,
            external_id=stub.external_id,
            canonical_url=stub.canonical_url,
            title=stub.question,
            document_type="ZIR_CONSULTATION",
            metadata={
                "src": stub.src,
                "zir_id": stub.id,
                "category": stub.category,
                "status": stub.status.value,
                "status_text": stub.status_text,
            },
        )

    def _stub_from_raw(self, item: RawDocument) -> ZirConsultationStub | None:
        if not item.external_id:
            return None
        src, zir_id = parse_external_id(item.external_id)
        return ZirConsultationStub(
            id=zir_id,
            external_id=item.external_id,
            question=item.title or "",
            category=item.metadata.get("category"),
            status=ZirStatus(item.metadata.get("status", ZirStatus.UNKNOWN)),
            status_text=item.metadata.get("status_text"),
            canonical_url=item.canonical_url or canonical_url(src, zir_id),
            src=src,
        )

    def _identity_from_item(self, item: RawDocument) -> tuple[str, str]:
        if item.external_id:
            return parse_external_id(item.external_id)
        if item.metadata.get("zir_id"):
            return str(item.metadata.get("src") or "ques"), str(item.metadata["zir_id"])
        if item.canonical_url:
            from app.sources.zir.parser import extract_id_from_url

            return extract_id_from_url(item.canonical_url)
        raise ValueError("ZIR RawDocument is missing external_id/zir_id/canonical_url")

    def _add_stubs(
        self,
        stubs: list[ZirConsultationStub],
        seen: set[str],
        new_stubs: list[ZirConsultationStub],
    ) -> int:
        added = 0
        for stub in new_stubs:
            if stub.external_id in seen:
                continue
            seen.add(stub.external_id)
            stubs.append(stub)
            added += 1
        return added
