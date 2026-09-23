import re

from app.sources.base import NormalizedDocument, RawDocument, SourceAdapter
from app.sources.dps.client import DpsClient, DpsHTTPError
from app.sources.dps.parser import (
    canonical_to_print_url,
    classify_document_type,
    external_id,
    extract_page_id,
    parse_attachments,
    parse_links_as_attachments,
    parse_list_page,
    parse_more_payload,
    parse_print_page,
)
from app.sources.dps.schemas import DpsDocumentStub, DpsDocumentType
from app.utils.normalization import normalize_legal_text

DEFAULT_SECTIONS = [
    "https://tax.gov.ua/media-tsentr/novini/",
    "https://www.tax.gov.ua/zakonodavstvo/podatkove-zakonodavstvo/nakazi/",
    "https://tax.gov.ua/zakonodavstvo/podatkove-zakonodavstvo/listi-dps/",
    (
        "https://tax.gov.ua/zakonodavstvo/podatki-ta-zbori/"
        "zagalnoderjavni-podatki/podatok-na-pributok-pidpri/formi-zvitnosti/"
    ),
]

KNOWN_REFERENCE_INDEX = {
    ("MINFIN_ORDER", "186"): "dps:80085",
    ("MINFIN_ORDER", "249"): "dps:80205",
    ("MINFIN_ORDER", "293"): "dps:80206",
    ("DPS_LETTER", "15504/7/99-00-21-02-01-07"): "dps:80200",
}

KNOWN_CANONICAL_URLS = {
    "80085": (
        "https://tax.gov.ua/zakonodavstvo/podatki-ta-zbori/"
        "zagalnoderjavni-podatki/podatok-na-pributok-pidpri/formi-zvitnosti/80085.html"
    ),
    "80205": "https://www.tax.gov.ua/zakonodavstvo/podatkove-zakonodavstvo/nakazi/80205.html",
    "80206": "https://www.tax.gov.ua/zakonodavstvo/podatkove-zakonodavstvo/nakazi/80206.html",
    "80200": "https://tax.gov.ua/zakonodavstvo/podatkove-zakonodavstvo/listi-dps/80200.html",
    "1025759": "https://tax.gov.ua/media-tsentr/novini/1025759.html",
}


class DpsAdapter(SourceAdapter):
    def __init__(
        self,
        client: DpsClient | None = None,
        sections: list[str] | None = None,
        max_pages_per_section: int = 2,
        discovery_limit: int | None = 50,
        reference_index: dict[tuple[str, str], str] | None = None,
    ) -> None:
        self.client = client or DpsClient()
        self.sections = sections or DEFAULT_SECTIONS
        self.max_pages_per_section = max_pages_per_section
        self.discovery_limit = discovery_limit
        self.reference_index = {**KNOWN_REFERENCE_INDEX, **(reference_index or {})}
        self._discovered_reference_index: dict[tuple[str, str], str] = {}

    @property
    def source_code(self) -> str:
        return "dps"

    async def fetch_items(self) -> list[RawDocument]:
        stubs: list[DpsDocumentStub] = []
        seen: set[str] = set()

        for section_url in self.sections:
            html = await self.client.get_text(section_url)
            section_stubs = parse_list_page(html, section_url)
            self._add_stubs(stubs, seen, section_stubs)

            for page in range(2, self.max_pages_per_section + 1):
                payload = await self.client.post_more(section_url, page=page, date_from="", date_to="")
                more_stubs = parse_more_payload(payload, section_url)
                if not more_stubs:
                    break
                self._add_stubs(stubs, seen, more_stubs)

        if self.discovery_limit is not None:
            stubs = stubs[: self.discovery_limit]
        self._discovered_reference_index = self._build_reference_index(stubs)
        return [self._stub_to_raw(stub) for stub in stubs]

    async def fetch_document(self, item: RawDocument) -> RawDocument:
        page_id = self._page_id_from_item(item)
        canonical_url = item.canonical_url or KNOWN_CANONICAL_URLS.get(page_id)
        if canonical_url is None:
            raise ValueError(f"DPS document {page_id} is missing canonical_url")

        print_url = item.metadata.get("print_url") or canonical_to_print_url(canonical_url)
        if not isinstance(print_url, str):
            raise ValueError(f"DPS document {page_id} print_url must be a string")

        try:
            normal_html = await self.client.get_text(canonical_url)
            attachments = parse_attachments(normal_html, canonical_url)
        except DpsHTTPError:
            attachments = []

        reference_index = {
            **self._discovered_reference_index,
            **self.reference_index,
        }
        try:
            print_html = await self.client.get_text(print_url)
            attachments = self._merge_attachments(
                attachments,
                parse_links_as_attachments(print_html, print_url),
            )
            page = parse_print_page(
                print_html,
                source_url=print_url,
                fallback_canonical_url=canonical_url,
                attachments=attachments,
                reference_index=reference_index,
            )
        except (DpsHTTPError, ValueError):
            normal_html = await self.client.get_text(canonical_url)
            attachments = self._merge_attachments(
                attachments,
                parse_links_as_attachments(normal_html, canonical_url),
            )
            page = parse_print_page(
                normal_html,
                source_url=canonical_url,
                fallback_canonical_url=canonical_url,
                attachments=attachments,
                reference_index=reference_index,
            )

        metadata = dict(item.metadata)
        metadata.update(
            {
                "page_id": page.page_id,
                "section": page.section,
                "author": page.author,
                "print_url": page.print_url,
                "source_url": page.source_url,
                "attachments": [attachment.model_dump(mode="json") for attachment in page.attachments],
                "references": [reference.model_dump(mode="json") for reference in page.references],
                "relation_candidates": [
                    candidate.model_dump(mode="json") for candidate in page.relation_candidates
                ],
            }
        )

        return RawDocument(
            source_code=self.source_code,
            external_id=page.external_id,
            canonical_url=page.canonical_url,
            title=page.title,
            content=page.body,
            document_type=page.document_type.value,
            published_at=page.published_at,
            effective_at=page.effective_at,
            metadata=metadata,
        )

    async def normalize(self, document: RawDocument) -> NormalizedDocument:
        if document.content is None:
            raise ValueError("DPS document content is required")
        if not document.external_id:
            raise ValueError("DPS document external_id is required")
        if not document.title:
            raise ValueError("DPS document title is required")

        return NormalizedDocument(
            source_code=self.source_code,
            external_id=document.external_id,
            canonical_url=document.canonical_url,
            title=document.title,
            content=normalize_legal_text(document.content),
            document_type=document.document_type,
            published_at=document.published_at,
            effective_at=document.effective_at,
            metadata=document.metadata,
        )

    async def fetch_by_page_id(self, page_id: str) -> RawDocument:
        canonical_url = KNOWN_CANONICAL_URLS.get(page_id)
        if canonical_url is None:
            raise ValueError(f"No known DPS canonical URL for page id {page_id}")
        return await self.fetch_document(
            RawDocument(
                source_code=self.source_code,
                external_id=external_id(page_id),
                canonical_url=canonical_url,
                metadata={
                    "page_id": page_id,
                    "print_url": canonical_to_print_url(canonical_url),
                },
            )
        )

    def _stub_to_raw(self, stub: DpsDocumentStub) -> RawDocument:
        return RawDocument(
            source_code=self.source_code,
            external_id=stub.external_id,
            canonical_url=stub.canonical_url,
            title=stub.title,
            document_type=stub.document_type.value,
            published_at=stub.published_at,
            metadata={
                "page_id": stub.page_id,
                "section": stub.section,
                "print_url": stub.print_url,
                "source_url": stub.source_url,
            },
        )

    def _add_stubs(
        self,
        stubs: list[DpsDocumentStub],
        seen: set[str],
        new_stubs: list[DpsDocumentStub],
    ) -> None:
        for stub in new_stubs:
            if stub.page_id in seen:
                continue
            seen.add(stub.page_id)
            stubs.append(stub)

    def _merge_attachments(self, *attachment_groups):
        merged = []
        seen = set()
        for group in attachment_groups:
            for attachment in group:
                if attachment.url in seen:
                    continue
                seen.add(attachment.url)
                merged.append(attachment)
        return merged

    def _build_reference_index(self, stubs: list[DpsDocumentStub]) -> dict[tuple[str, str], str]:
        index: dict[tuple[str, str], str] = {}
        for stub in stubs:
            if stub.document_type == DpsDocumentType.LETTER:
                match = _LETTER_TITLE_RE.search(stub.title)
                if match:
                    index.setdefault(("DPS_LETTER", match.group("number")), stub.external_id)
            if stub.document_type in {DpsDocumentType.ORDER, DpsDocumentType.REPORTING_FORM}:
                match = _ORDER_TITLE_RE.search(stub.title)
                if match:
                    index.setdefault(("MINFIN_ORDER", match.group("number")), stub.external_id)
        return index

    def _page_id_from_item(self, item: RawDocument) -> str:
        metadata_page_id = item.metadata.get("page_id")
        if metadata_page_id:
            return str(metadata_page_id)
        if item.external_id and item.external_id.startswith("dps:"):
            return item.external_id.split(":", 1)[1]
        if item.canonical_url:
            return extract_page_id(item.canonical_url)
        raise ValueError("DPS RawDocument is missing page_id/external_id/canonical_url")


_ORDER_TITLE_RE = re.compile(r"№\s*(?P<number>\d+)")
_LETTER_TITLE_RE = re.compile(r"№\s*(?P<number>[\d/-]+)")
