from __future__ import annotations

import logging

from app.sources.base import NormalizedDocument, RawDocument, SourceAdapter
from app.sources.minfin.client import MinfinAccessBlockedError, MinfinClient, MinfinHTTPError
from app.sources.minfin.parser import (
    canonical_url,
    classify_document_type,
    date_to_datetime,
    external_id_from_url,
    parse_consultation_table,
    parse_news_list,
    parse_order_table,
    parse_page,
    semantic_content,
)
from app.sources.minfin.schemas import MinfinConsultationStub, MinfinDocumentStub, MinfinOrderStub
from app.utils.normalization import normalize_legal_text

logger = logging.getLogger(__name__)

DEFAULT_SECTIONS = [
    "https://mof.gov.ua/uk/orders_of_the_Ministry_of_Finance_of_Ukraine_in_2026.",
    "https://mof.gov.ua/uk/set-of-summarizing-tax-consultations",
    "https://mof.gov.ua/uk/crs-578",
    "https://mof.gov.ua/uk/clarification-641",
    "https://mof.gov.ua/uk/accounting",
    "https://mof.gov.ua/uk/nacionalni-polozhennja1",
    "https://mof.gov.ua/uk/nacionalni-polozhennja",
    "https://mof.gov.ua/uk/zagalni-rozjasnennja-fin-zvitnosti",
    "https://mof.gov.ua/uk/zagalni-roz_jasnennja",
    "https://mof.gov.ua/uk/Draft_regulatory_legal_acts_in_2026",
    "https://mof.gov.ua/uk/news",
]


class MinfinAdapter(SourceAdapter):
    def __init__(
        self,
        client: MinfinClient | None = None,
        sections: list[str] | None = None,
        discovery_limit: int | None = 50,
    ) -> None:
        self.client = client or MinfinClient()
        self.sections = sections or DEFAULT_SECTIONS
        self.discovery_limit = discovery_limit
        self.access_failures: list[dict[str, str | int]] = []

    @property
    def source_code(self) -> str:
        return "minfin"

    async def fetch_items(self) -> list[RawDocument]:
        self.access_failures = []
        items: list[RawDocument] = []
        seen: set[str] = set()
        for section_url in self.sections:
            try:
                html = await self.client.get_text(section_url)
            except MinfinAccessBlockedError as exc:
                self.access_failures.append(
                    {
                        "url": exc.url,
                        "status_code": exc.status_code,
                        "classification": exc.access_classification,
                    }
                )
                logger.warning("minfin_section_access_blocked url=%s", section_url)
                continue
            except MinfinHTTPError as exc:
                logger.warning("minfin_section_fetch_failed url=%s status=%s", section_url, exc.status_code)
                continue

            parsed_items = self._parse_section(section_url, html)
            for item in parsed_items:
                if item.external_id in seen:
                    continue
                seen.add(item.external_id)
                items.append(item)
                if self.discovery_limit is not None and len(items) >= self.discovery_limit:
                    return items
        return items

    async def fetch_document(self, item: RawDocument) -> RawDocument:
        if item.metadata.get("row_level") is True or item.content is not None:
            return item
        if not item.canonical_url:
            raise ValueError("Minfin RawDocument is missing canonical_url")
        html = await self.client.get_text(item.canonical_url)
        page = parse_page(html, item.canonical_url)
        content = semantic_content(
            title=page.title,
            body=page.body,
            attachments=page.attachments,
            references=page.references,
        )
        metadata = dict(item.metadata)
        metadata.update(
            {
                "source_url": page.source_url,
                "path": page.canonical_url,
                "attachments": [attachment.model_dump(mode="json") for attachment in page.attachments],
                "references": [reference.model_dump(mode="json") for reference in page.references],
            }
        )
        return RawDocument(
            source_code=self.source_code,
            external_id=page.external_id,
            canonical_url=page.canonical_url,
            title=page.title,
            content=content,
            document_type=page.document_type.value,
            published_at=page.published_at or item.published_at,
            effective_at=page.effective_at,
            metadata=metadata,
        )

    async def normalize(self, document: RawDocument) -> NormalizedDocument:
        if document.content is None:
            raise ValueError("Minfin document content is required")
        if not document.external_id:
            raise ValueError("Minfin document external_id is required")
        if not document.title:
            raise ValueError("Minfin document title is required")
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

    async def fetch_by_url(self, url: str) -> RawDocument:
        raw = RawDocument(
            source_code=self.source_code,
            external_id=external_id_from_url(url),
            canonical_url=canonical_url(url),
            document_type=classify_document_type(url).value,
            metadata={"source_url": url},
        )
        return await self.fetch_document(raw)

    def _parse_section(self, section_url: str, html: str) -> list[RawDocument]:
        normalized_url = canonical_url(section_url)
        lower = normalized_url.lower()
        if "orders_of_the_ministry_of_finance_of_ukraine_in_2026" in lower:
            return [self._order_to_raw(stub) for stub in parse_order_table(html, section_url)]
        if "set-of-summarizing-tax-consultations" in lower:
            return [self._consultation_to_raw(stub) for stub in parse_consultation_table(html, section_url)]
        if lower.rstrip("/").endswith("/uk/news"):
            return [self._stub_to_raw(stub) for stub in parse_news_list(html, section_url)]
        page = parse_page(html, section_url)
        content = semantic_content(
            title=page.title,
            body=page.body,
            attachments=page.attachments,
            references=page.references,
        )
        return [
            RawDocument(
                source_code=self.source_code,
                external_id=page.external_id,
                canonical_url=page.canonical_url,
                title=page.title,
                content=content,
                document_type=page.document_type.value,
                published_at=page.published_at,
                effective_at=page.effective_at,
                metadata={
                    "source_url": section_url,
                    "path": page.canonical_url,
                    "attachments": [attachment.model_dump(mode="json") for attachment in page.attachments],
                    "references": [reference.model_dump(mode="json") for reference in page.references],
                },
            )
        ]

    def _stub_to_raw(self, stub: MinfinDocumentStub) -> RawDocument:
        return RawDocument(
            source_code=self.source_code,
            external_id=stub.external_id,
            canonical_url=stub.canonical_url,
            title=stub.title,
            document_type=stub.document_type.value,
            published_at=stub.published_at,
            metadata={
                **stub.metadata,
                "source_url": stub.source_url,
                "section": stub.source_url,
            },
        )

    def _order_to_raw(self, stub: MinfinOrderStub) -> RawDocument:
        content = semantic_content(
            title=stub.title,
            body=stub.title,
            row_date=stub.row_date,
            order_date=stub.order_date,
            order_number=stub.order_number,
            attachments=stub.attachments,
            references=stub.references,
        )
        return RawDocument(
            source_code=self.source_code,
            external_id=stub.external_id,
            canonical_url=stub.canonical_url,
            title=stub.title,
            content=content,
            document_type=stub.document_type.value,
            published_at=date_to_datetime(stub.row_date),
            metadata={
                "row_level": True,
                "source_url": stub.source_url,
                "row_date": stub.row_date.isoformat() if stub.row_date else None,
                "order_date": stub.order_date.isoformat(),
                "order_number": stub.order_number,
                "attachments": [attachment.model_dump(mode="json") for attachment in stub.attachments],
                "references": [reference.model_dump(mode="json") for reference in stub.references],
            },
        )

    def _consultation_to_raw(self, stub: MinfinConsultationStub) -> RawDocument:
        content = semantic_content(
            title=stub.title,
            body=stub.title,
            row_date=stub.row_date,
            order_date=stub.order_date,
            order_number=stub.order_number,
            attachments=stub.attachments,
            references=stub.references,
            tax_code_references=stub.tax_code_references,
        )
        return RawDocument(
            source_code=self.source_code,
            external_id=stub.external_id,
            canonical_url=stub.canonical_url,
            title=stub.title,
            content=content,
            document_type=stub.document_type.value,
            published_at=date_to_datetime(stub.row_date),
            metadata={
                "row_level": True,
                "source_url": stub.source_url,
                "row_date": stub.row_date.isoformat() if stub.row_date else None,
                "order_date": stub.order_date.isoformat(),
                "order_number": stub.order_number,
                "attachments": [attachment.model_dump(mode="json") for attachment in stub.attachments],
                "references": [reference.model_dump(mode="json") for reference in stub.references],
                "tax_code_references": stub.tax_code_references,
            },
        )
