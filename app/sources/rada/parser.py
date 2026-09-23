import logging
import re
from datetime import date
from html import unescape
from html.parser import HTMLParser
from typing import Any

from app.models.enums import RelationType
from app.sources.rada.schemas import (
    RadaCard,
    RadaDocumentStub,
    RadaRevision,
    RadaRevisionState,
    SourceRelationCandidate,
)

logger = logging.getLogger(__name__)

TYPE_NAMES = {
    1: "Закон",
    2: "Постанова",
    9: "Наказ",
    12: "Роз'яснення",
    15: "Лист",
    21: "Кодекс України",
    95: "Повідомлення",
    124: "Кодекс",
}


def parse_yyyymmdd(value: Any) -> date | None:
    if value in (None, ""):
        return None
    text = str(value)
    if not re.fullmatch(r"\d{8}", text):
        logger.warning("rada_date_parse_failed value=%s", value)
        return None
    try:
        return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    except ValueError:
        logger.warning("rada_date_parse_failed value=%s", value)
        return None


def parse_basis_nregs(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    return [part.strip() for part in str(value).split(",") if part.strip()]


def parse_type_ids(value: Any) -> list[int]:
    if value in (None, ""):
        return []
    parts = str(value).split("|")
    type_ids: list[int] = []
    for part in parts:
        try:
            type_ids.append(int(part))
        except ValueError:
            logger.warning("rada_type_parse_failed value=%s", value)
    return type_ids


def parse_organs(value: Any) -> tuple[int | None, date | None, str | None]:
    if value in (None, ""):
        return None, None, None
    first = str(value).split("|")[0]
    parts = first.split(":", 2)
    if len(parts) < 3:
        logger.warning("rada_organs_parse_failed value=%s", value)
        return None, None, None
    try:
        issuer_id = int(parts[0])
    except ValueError:
        logger.warning("rada_organs_parse_failed value=%s", value)
        issuer_id = None
    return issuer_id, parse_yyyymmdd(parts[1]), parts[2] or None


def document_type_from_ids(type_ids: list[int]) -> str | None:
    for type_id in type_ids:
        if type_id in TYPE_NAMES:
            return TYPE_NAMES[type_id]
    return None


def classify_revision(revision_date: date, current_revision_date: date | None) -> RadaRevisionState:
    if current_revision_date is None:
        return RadaRevisionState.CURRENT
    if revision_date < current_revision_date:
        return RadaRevisionState.PREVIOUS
    if revision_date > current_revision_date:
        return RadaRevisionState.FUTURE
    return RadaRevisionState.CURRENT


def parse_revisions(
    items: list[dict[str, Any]] | None, current_revision_date: date | None, target_nreg: str
) -> list[RadaRevision]:
    revisions: list[RadaRevision] = []
    for item in items or []:
        revision_date = parse_yyyymmdd(item.get("datred"))
        if revision_date is None:
            continue
        basis_nregs = parse_basis_nregs(item.get("pidstava"))
        revisions.append(
            RadaRevision(
                date=revision_date,
                basis_nregs=basis_nregs,
                event_type=_int_or_none(item.get("podid")),
                format=_int_or_none(item.get("format")),
                pages=_int_or_none(item.get("pages")),
                size=_int_or_none(item.get("size")),
                state=classify_revision(revision_date, current_revision_date),
            )
        )
    return sorted(revisions, key=lambda revision: revision.date)


def parse_effective_date(card_json: dict[str, Any]) -> date | None:
    hist = card_json.get("hist")
    if isinstance(hist, list):
        for event in hist:
            if _int_or_none(event.get("podid")) == 1:
                return parse_yyyymmdd(event.get("poddat"))

    history = card_json.get("history")
    if isinstance(history, str):
        for chunk in history.split("|"):
            parts = chunk.split(":")
            if len(parts) >= 2 and parts[1] == "1":
                return parse_yyyymmdd(parts[0])
    return None


def parse_publication_date(card_json: dict[str, Any]) -> date | None:
    publics = card_json.get("publics")
    if isinstance(publics, list) and publics:
        dates = [parse_yyyymmdd(item.get("pubdat")) for item in publics if isinstance(item, dict)]
        dates = [item for item in dates if item is not None]
        return min(dates) if dates else None
    return None


def parse_card(card_json: dict[str, Any], current_card_json: dict[str, Any] | None = None) -> RadaCard:
    current_source = current_card_json or card_json
    nreg = str(card_json.get("nreg") or current_source.get("nreg") or "")
    if not nreg:
        raise ValueError("Rada card is missing nreg")

    title = str(card_json.get("nazva") or current_source.get("nazva") or "").strip()
    if not title:
        raise ValueError(f"Rada card {nreg} is missing title")

    current_revision_date = parse_yyyymmdd(current_source.get("datred"))
    issuer_id, adoption_date, document_number = parse_organs(
        card_json.get("organs") or current_source.get("organs")
    )
    type_ids = parse_type_ids(card_json.get("types") or current_source.get("types"))
    basis_nregs = parse_basis_nregs(card_json.get("pidstava"))
    current_revision_basis_nregs = parse_basis_nregs(current_source.get("pidstava"))
    specific_revision_basis_nregs = basis_nregs
    revisions = parse_revisions(current_source.get("eds"), current_revision_date, nreg)

    relation_candidates = build_basis_relation_candidates(
        nreg=nreg,
        basis_nregs=specific_revision_basis_nregs,
        revision_date=card_json.get("datred"),
        basis_scope="specific_revision" if current_card_json else "current_revision",
    )
    historical_relation_candidates = build_historical_relation_candidates(
        nreg=nreg,
        revisions=revisions,
    )

    return RadaCard(
        nreg=nreg,
        dokid=_int_or_none(card_json.get("dokid") or current_source.get("dokid")),
        title=title,
        status_id=_int_or_none(card_json.get("status") or current_source.get("status")),
        type_ids=type_ids,
        document_type=document_type_from_ids(type_ids),
        issuer_id=issuer_id,
        adoption_date=adoption_date,
        document_number=document_number,
        current_revision_date=current_revision_date,
        basis_nregs=basis_nregs,
        current_revision_basis_nregs=current_revision_basis_nregs,
        specific_revision_basis_nregs=specific_revision_basis_nregs,
        effective_date=parse_effective_date(card_json),
        publication_date=parse_publication_date(card_json),
        revisions=revisions,
        relation_candidates=relation_candidates,
        historical_relation_candidates=historical_relation_candidates,
        raw_metadata=_compact_card_metadata(card_json, current_revision_date, revisions),
    )


def parse_updated_documents(payload: dict[str, Any]) -> list[RadaDocumentStub]:
    stubs: list[RadaDocumentStub] = []
    for item in payload.get("list") or []:
        if not isinstance(item, dict):
            continue
        nreg = item.get("nreg")
        if not nreg:
            continue
        issuer_id, adoption_date, document_number = parse_organs(item.get("organs"))
        stubs.append(
            RadaDocumentStub(
                nreg=str(nreg),
                title=item.get("nazva"),
                dokid=_int_or_none(item.get("dokid")),
                status_id=_int_or_none(item.get("status")),
                type_ids=parse_type_ids(item.get("types") or item.get("typ")),
                issuer_id=issuer_id,
                adoption_date=adoption_date,
                document_number=document_number,
                event_date=parse_yyyymmdd(item.get("poddat")),
                publication_date=parse_yyyymmdd(item.get("pridat")),
                raw={
                    "block": payload.get("block"),
                    "num": item.get("num"),
                    "orgdat": item.get("orgdat"),
                    "orgnum": item.get("orgnum"),
                    "typ": item.get("typ"),
                },
            )
        )
    return stubs


def build_basis_relation_candidates(
    nreg: str,
    basis_nregs: list[str],
    revision_date: Any | None = None,
    basis_scope: str = "revision",
) -> list[SourceRelationCandidate]:
    candidates: list[SourceRelationCandidate] = []
    seen: set[tuple[str, str]] = set()

    def add_candidate(basis_nreg: str, metadata: dict[str, Any]) -> None:
        key = (basis_nreg, nreg)
        if key in seen:
            return
        seen.add(key)
        candidates.append(
            SourceRelationCandidate(
                from_external_id=basis_nreg,
                to_external_id=nreg,
                relation_type=RelationType.AMENDS,
                metadata=metadata,
            )
        )

    for basis_nreg in basis_nregs:
        add_candidate(
            basis_nreg,
            {
                "basis_scope": basis_scope,
                "basis_for_revision_date": str(revision_date) if revision_date else None,
                "deterministic": True,
                "explicit": True,
            },
        )
    return candidates


def build_historical_relation_candidates(
    nreg: str,
    revisions: list[RadaRevision],
) -> list[SourceRelationCandidate]:
    candidates: list[SourceRelationCandidate] = []
    seen: set[tuple[str, str, str]] = set()

    for revision in revisions:
        for basis_nreg in revision.basis_nregs:
            key = (basis_nreg, nreg, revision.date.isoformat())
            if key in seen:
                continue
            seen.add(key)
            candidates.append(
                SourceRelationCandidate(
                    from_external_id=basis_nreg,
                    to_external_id=nreg,
                    relation_type=RelationType.AMENDS,
                    metadata={
                        "basis_scope": "revision_history",
                        "basis_for_revision_date": revision.date.isoformat(),
                        "revision_state": revision.state.value,
                        "deterministic": True,
                        "explicit": True,
                    },
                )
            )
    return candidates


def extract_article_text(html: str) -> str:
    extractor = _ArticleTextExtractor()
    extractor.feed(html)
    text = extractor.text()
    if not text:
        raise ValueError("Rada HTML does not contain extractable div#article text")
    if "Відбувається форматування тексту" in text and len(text) < 1000:
        raise ValueError("Rada HTML contains only a text loading placeholder")
    return text


class _ArticleTextExtractor(HTMLParser):
    block_tags = {"p", "div", "tr", "table", "h1", "h2", "h3", "h4", "h5", "li", "br"}
    skip_tags = {"script", "style", "noscript", "img"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._in_article = False
        self._article_depth = 0
        self._skip_depth = 0
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        if tag == "div" and attrs_dict.get("id") == "article":
            self._in_article = True
            self._article_depth = 1
            return
        if not self._in_article:
            return
        self._article_depth += 1
        if tag in self.skip_tags:
            self._skip_depth += 1
        if tag == "a" and attrs_dict.get("name"):
            self._append_newline()
        if tag in self.block_tags:
            self._append_newline()

    def handle_endtag(self, tag: str) -> None:
        if not self._in_article:
            return
        if tag in self.skip_tags and self._skip_depth:
            self._skip_depth -= 1
        if tag in self.block_tags:
            self._append_newline()
        self._article_depth -= 1
        if self._article_depth <= 0:
            self._in_article = False

    def handle_data(self, data: str) -> None:
        if self._in_article and not self._skip_depth:
            cleaned = re.sub(r"[ \t\r\n\f\v]+", " ", unescape(data)).strip()
            if cleaned and cleaned != "[ image ]":
                self._chunks.append(cleaned)
                self._chunks.append(" ")

    def text(self) -> str:
        text = "".join(self._chunks)
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n[ \t]+", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"[ \t]{2,}", " ", text)
        return text.strip()

    def _append_newline(self) -> None:
        if self._chunks and self._chunks[-1] != "\n":
            self._chunks.append("\n")


def _int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _compact_card_metadata(
    card_json: dict[str, Any],
    current_revision_date: date | None,
    revisions: list[RadaRevision],
) -> dict[str, Any]:
    return {
        "dokid": card_json.get("dokid"),
        "status_id": card_json.get("status"),
        "types_raw": card_json.get("types"),
        "organs_raw": card_json.get("organs"),
        "current_revision_date": current_revision_date.isoformat()
        if current_revision_date
        else None,
        "revision_count": card_json.get("edcnt"),
        "basis_raw": card_json.get("pidstava"),
        "revisions": [revision.model_dump(mode="json") for revision in revisions],
        "history": card_json.get("hist"),
    }
