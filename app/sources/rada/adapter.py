from datetime import date, datetime, time, timezone
from typing import Any

from app.sources.base import NormalizedDocument, RawDocument, SourceAdapter
from app.sources.rada.client import RadaClient, RadaHTTPError
from app.sources.rada.parser import extract_article_text, parse_card, parse_updated_documents
from app.sources.rada.schemas import RadaCard, RadaDocumentStub
from app.utils.normalization import normalize_legal_text


class RadaAdapter(SourceAdapter):
    def __init__(self, client: RadaClient | None = None, discovery_limit: int | None = 50) -> None:
        self.client = client or RadaClient()
        self.discovery_limit = discovery_limit

    @property
    def source_code(self) -> str:
        return "rada"

    async def fetch_items(self) -> list[RawDocument]:
        payload = await self.client.get_updated_documents()
        stubs = parse_updated_documents(payload)
        if self.discovery_limit is not None:
            stubs = stubs[: self.discovery_limit]
        return [self._stub_to_raw(stub) for stub in stubs]

    async def fetch_document(self, item: RawDocument) -> RawDocument:
        nreg = item.external_id
        if not nreg:
            raise ValueError("Rada RawDocument is missing external_id/nreg")

        revision_date = item.metadata.get("revision_date")
        revision_date_text = str(revision_date).replace("-", "") if revision_date else None

        current_card_json = await self.client.get_card(nreg)
        selected_card_json = (
            await self.client.get_card(nreg, revision_date_text)
            if revision_date_text
            else current_card_json
        )
        card = parse_card(selected_card_json, current_card_json=current_card_json)

        try:
            html = await self.client.get_document_html(nreg, revision_date_text)
            article_text = extract_article_text(html)
        except (RadaHTTPError, ValueError):
            html = await self.client.get_print_html(nreg, revision_date_text)
            article_text = extract_article_text(html)

        metadata = dict(item.metadata)
        metadata.update(self._card_metadata(card, selected_card_json, revision_date_text))

        return RawDocument(
            source_code=self.source_code,
            external_id=card.nreg,
            canonical_url=self._canonical_url(card.nreg, revision_date_text),
            title=card.title,
            content=article_text,
            document_type=card.document_type,
            published_at=_date_to_datetime(card.publication_date),
            effective_at=_date_to_datetime(card.effective_date),
            metadata=metadata,
        )

    async def normalize(self, document: RawDocument) -> NormalizedDocument:
        if document.content is None:
            raise ValueError("Rada document content is required")
        if not document.external_id:
            raise ValueError("Rada document external_id/nreg is required")
        if not document.title:
            raise ValueError("Rada document title is required")

        return NormalizedDocument(
            source_code=self.source_code,
            external_id=document.external_id,
            canonical_url=document.canonical_url or self._canonical_url(document.external_id),
            title=document.title,
            content=normalize_legal_text(document.content),
            document_type=document.document_type,
            published_at=document.published_at,
            effective_at=document.effective_at,
            metadata=document.metadata,
        )

    async def fetch_by_nreg(self, nreg: str, revision_date: date | str | None = None) -> RawDocument:
        raw = RawDocument(
            source_code=self.source_code,
            external_id=nreg,
            canonical_url=self._canonical_url(nreg),
            metadata={
                "revision_date": revision_date.isoformat()
                if isinstance(revision_date, date)
                else revision_date
            },
        )
        return await self.fetch_document(raw)

    def _stub_to_raw(self, stub: RadaDocumentStub) -> RawDocument:
        return RawDocument(
            source_code=self.source_code,
            external_id=stub.nreg,
            canonical_url=self._canonical_url(stub.nreg),
            title=stub.title,
            document_type=None,
            published_at=_date_to_datetime(stub.publication_date),
            metadata={
                "dokid": stub.dokid,
                "document_number": stub.document_number,
                "issuer_id": stub.issuer_id,
                "adoption_date": stub.adoption_date.isoformat() if stub.adoption_date else None,
                "status_id": stub.status_id,
                "type_ids": stub.type_ids,
                "event_date": stub.event_date.isoformat() if stub.event_date else None,
                "discovery": stub.raw,
            },
        )

    def _card_metadata(
        self,
        card: RadaCard,
        selected_card_json: dict[str, Any],
        requested_revision_date: str | None,
    ) -> dict[str, Any]:
        return {
            "dokid": card.dokid,
            "document_number": card.document_number,
            "issuer_id": card.issuer_id,
            "adoption_date": card.adoption_date.isoformat() if card.adoption_date else None,
            "status_id": card.status_id,
            "types": card.type_ids,
            "current_revision_date": card.current_revision_date.isoformat()
            if card.current_revision_date
            else None,
            "revision_date": parse_card_revision_date(selected_card_json),
            "requested_revision_date": requested_revision_date,
            "basis_nregs": card.basis_nregs,
            "current_revision_basis_nregs": card.current_revision_basis_nregs,
            "specific_revision_basis_nregs": card.specific_revision_basis_nregs,
            "revisions": [revision.model_dump(mode="json") for revision in card.revisions],
            "relation_candidates": [
                candidate.model_dump(mode="json") for candidate in card.relation_candidates
            ],
            "historical_relation_candidates": [
                candidate.model_dump(mode="json")
                for candidate in card.historical_relation_candidates
            ],
            "rada": card.raw_metadata,
        }

    def _canonical_url(self, nreg: str, revision_date: str | None = None) -> str:
        suffix = f"/ed{revision_date}" if revision_date else ""
        return f"https://zakon.rada.gov.ua/laws/show/{nreg}{suffix}"


def parse_card_revision_date(card_json: dict[str, Any]) -> str | None:
    value = card_json.get("datred")
    if not value:
        return None
    text = str(value)
    if len(text) != 8:
        return text
    return f"{text[:4]}-{text[4:6]}-{text[6:8]}"


def _date_to_datetime(value: date | None) -> datetime | None:
    if value is None:
        return None
    return datetime.combine(value, time.min, tzinfo=timezone.utc)
