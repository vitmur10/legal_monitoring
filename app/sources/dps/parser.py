import json
import logging
import re
from datetime import date, datetime, time, timezone
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlparse

from app.models.enums import RelationType
from app.sources.dps.schemas import (
    DpsAttachment,
    DpsDocumentReference,
    DpsDocumentStub,
    DpsDocumentType,
    DpsPageMetadata,
    DpsRelationCandidate,
)

logger = logging.getLogger(__name__)

PAGE_ID_RE = re.compile(r"(?:^|/)(?:print-)?(?P<id>\d{4,8})\.html(?:$|[?#])")
ATTACHMENT_RE = re.compile(
    r"\.(?P<extension>pdf|docx?|xlsx?|xls|zip|xml)(?:$|[?#])",
    flags=re.I,
)
SIZE_RE = re.compile(r"\(\.?(?P<extension>pdf|docx?|xlsx?|xls|zip|xml),\s*(?P<size>[^)]+)\)", re.I)
MINFIN_ORDER_RE = re.compile(
    r"(?P<evidence>(?:наказ(?:ом|у)?\s+)?Міністерства\s+фінансів\s+України\s+"
    r"від\s+(?P<date>\d{1,2}\.\d{1,2}\.\d{4}|\d{1,2}\s+[а-яіїєґ]+\s+\d{4}\s+року?)\s+"
    r"№\s*(?P<number>\d+))",
    re.I,
)
DPS_LETTER_RE = re.compile(
    r"(?P<evidence>Лист\s+ДПС\s+від\s+"
    r"(?P<date>\d{1,2}\.\d{1,2}\.\d{4}|\d{1,2}\s+[а-яіїєґ]+\s+\d{4}\s+року?)\s+"
    r"№\s*(?P<number>[\d/-]+))",
    re.I,
)

MONTHS = {
    "січня": 1,
    "лютого": 2,
    "березня": 3,
    "квітня": 4,
    "травня": 5,
    "червня": 6,
    "липня": 7,
    "серпня": 8,
    "вересня": 9,
    "жовтня": 10,
    "листопада": 11,
    "грудня": 12,
}


def external_id(page_id: str) -> str:
    return f"dps:{page_id}"


def extract_page_id(url: str) -> str:
    match = PAGE_ID_RE.search(url)
    if not match:
        raise ValueError(f"DPS URL does not contain a numeric page id: {url}")
    return match.group("id")


def canonical_to_print_url(url: str) -> str:
    if re.search(r"/print-\d{4,8}\.html(?:$|[?#])", url):
        return url
    return re.sub(r"/(\d{4,8}\.html(?:$|[?#])?)", r"/print-\1", url, count=1)


def print_to_canonical_url(url: str) -> str:
    return re.sub(r"/print-(\d{4,8}\.html(?:$|[?#])?)", r"/\1", url, count=1)


def classify_document_type(url: str, section: str | None = None) -> DpsDocumentType:
    text = f"{url} {section or ''}".lower()
    if "/media-tsentr/novini/" in text or "новини" in text:
        return DpsDocumentType.NEWS
    if "/nakazi/" in text or "накази" in text:
        return DpsDocumentType.ORDER
    if "/listi-dps/" in text or "/listi/" in text or "листи" in text:
        return DpsDocumentType.LETTER
    if "/formi-zvitnosti/" in text or "форми звітності" in text:
        return DpsDocumentType.REPORTING_FORM
    return DpsDocumentType.OTHER


def parse_ukrainian_published_at(value: str | None) -> datetime | None:
    if not value:
        return None
    text = re.sub(r"\s+", " ", unescape(value)).strip().lower()
    match = re.search(
        r"(?P<day>\d{1,2})\s+(?P<month>[а-яіїєґ]+)\s+(?P<year>\d{4})\s+о\s+"
        r"(?P<hour>\d{1,2}):(?P<minute>\d{2})",
        text,
        flags=re.I,
    )
    if not match:
        return None
    month = MONTHS.get(match.group("month"))
    if month is None:
        return None
    return datetime(
        int(match.group("year")),
        month,
        int(match.group("day")),
        int(match.group("hour")),
        int(match.group("minute")),
        tzinfo=timezone.utc,
    )


def parse_source_date(value: str | None) -> date | None:
    if not value:
        return None
    text = re.sub(r"\s+", " ", value.lower().replace("року", "")).strip()
    numeric = re.fullmatch(r"(?P<day>\d{1,2})\.(?P<month>\d{1,2})\.(?P<year>\d{4})", text)
    if numeric:
        return _date_or_none(
            int(numeric.group("year")),
            int(numeric.group("month")),
            int(numeric.group("day")),
        )
    named = re.fullmatch(r"(?P<day>\d{1,2})\s+(?P<month>[а-яіїєґ]+)\s+(?P<year>\d{4})", text)
    if named and named.group("month") in MONTHS:
        return _date_or_none(
            int(named.group("year")),
            MONTHS[named.group("month")],
            int(named.group("day")),
        )
    return None


def parse_list_page(html: str, section_url: str) -> list[DpsDocumentStub]:
    return _parse_list_fragment(html, section_url)


def parse_more_payload(payload: dict[str, Any], section_url: str) -> list[DpsDocumentStub]:
    feed = payload.get("feed")
    if not isinstance(feed, str) or not feed.strip():
        return []
    return _parse_list_fragment(feed, section_url)


def parse_more_json(text: str, section_url: str) -> list[DpsDocumentStub]:
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("DPS more response must be a JSON object")
    return parse_more_payload(payload, section_url)


def parse_print_page(
    html: str,
    source_url: str,
    fallback_canonical_url: str | None = None,
    attachments: list[DpsAttachment] | None = None,
    reference_index: dict[tuple[str, str], str] | None = None,
) -> DpsPageMetadata:
    page_id = extract_page_id(source_url)
    print_url = canonical_to_print_url(source_url)
    canonical_url = _extract_footer_canonical_url(html) or fallback_canonical_url or print_to_canonical_url(print_url)
    cleaned_html = _remove_scripts_and_styles(html)
    print_html = _extract_print_container(cleaned_html)
    text = html_to_text(print_html)

    if "Access Denied" in text[:300]:
        raise ValueError(f"DPS access denied page returned for {source_url}")

    title = _extract_title(cleaned_html, text)
    published_at = parse_ukrainian_published_at(_first_match(r"опубліковано\s+([^<\n]+)", cleaned_html))
    section = _first_match(r"Розділ:\s*([^<\n]+)", cleaned_html)
    author = _extract_author(text)
    body = _extract_body_text(text)
    references = parse_document_references(f"{title}\n{body}", reference_index=reference_index)
    effective_at = _extract_effective_at(body)

    return DpsPageMetadata(
        page_id=page_id,
        external_id=external_id(page_id),
        title=title,
        canonical_url=canonical_url,
        print_url=print_url,
        source_url=source_url,
        section=section,
        author=author,
        document_type=classify_document_type(canonical_url, section),
        published_at=published_at,
        effective_at=effective_at,
        body=body,
        attachments=attachments or [],
        references=references,
        relation_candidates=build_relation_candidates(
            page_id=page_id,
            document_type=classify_document_type(canonical_url, section),
            title=title,
            body=body,
            references=references,
        ),
    )


def parse_attachments(html: str, page_url: str) -> list[DpsAttachment]:
    additional = _extract_class_container(html, "materials-additional")
    if additional is None:
        return []
    return parse_links_as_attachments(additional, page_url)


def parse_links_as_attachments(html: str, page_url: str) -> list[DpsAttachment]:
    parser = _LinkExtractor()
    parser.feed(html)
    attachments: list[DpsAttachment] = []
    seen: set[str] = set()
    for href, label in parser.links:
        absolute_url = urljoin(page_url, href)
        match = ATTACHMENT_RE.search(absolute_url)
        if not match or absolute_url in seen:
            continue
        seen.add(absolute_url)
        size_match = SIZE_RE.search(label)
        attachments.append(
            DpsAttachment(
                url=absolute_url,
                label=_clean_text(label).removesuffix("(Завантажити)").strip(),
                extension=match.group("extension").lower(),
                size_text=size_match.group("size").strip() if size_match else None,
            )
        )
    return attachments


def parse_document_references(
    text: str,
    reference_index: dict[tuple[str, str], str] | None = None,
) -> list[DpsDocumentReference]:
    references: list[DpsDocumentReference] = []
    seen: set[tuple[str, str, str | None]] = set()

    for match in MINFIN_ORDER_RE.finditer(text):
        number = match.group("number")
        ref_date = parse_source_date(match.group("date"))
        key = ("MINFIN_ORDER", number, ref_date.isoformat() if ref_date else None)
        if key in seen:
            continue
        seen.add(key)
        references.append(
            DpsDocumentReference(
                document_kind="ORDER",
                issuer="MINFIN",
                number=number,
                date=ref_date,
                external_id=_resolve_reference(reference_index, "MINFIN_ORDER", number),
                evidence=_clean_text(match.group("evidence")),
            )
        )

    for match in DPS_LETTER_RE.finditer(text):
        number = match.group("number")
        ref_date = parse_source_date(match.group("date"))
        key = ("DPS_LETTER", number, ref_date.isoformat() if ref_date else None)
        if key in seen:
            continue
        seen.add(key)
        references.append(
            DpsDocumentReference(
                document_kind="LETTER",
                issuer="DPS",
                number=number,
                date=ref_date,
                external_id=_resolve_reference(reference_index, "DPS_LETTER", number),
                evidence=_clean_text(match.group("evidence")),
            )
        )
    return references


def build_relation_candidates(
    page_id: str,
    document_type: DpsDocumentType,
    title: str,
    body: str,
    references: list[DpsDocumentReference],
) -> list[DpsRelationCandidate]:
    candidates: list[DpsRelationCandidate] = []
    own_external_id = external_id(page_id)
    seen: set[tuple[str, str, RelationType]] = set()

    if document_type == DpsDocumentType.ORDER and "внесення змін до наказ" in title.lower():
        amend_target_numbers = _extract_amended_order_numbers(f"{title}\n{body}")
        for reference in references:
            if (
                reference.document_kind == "ORDER"
                and reference.number in amend_target_numbers
                and reference.external_id
                and reference.external_id != own_external_id
            ):
                _add_relation_candidate(
                    candidates,
                    seen,
                    own_external_id,
                    reference.external_id,
                    RelationType.AMENDS,
                    reference,
                )

    if document_type == DpsDocumentType.LETTER:
        for reference in references:
            if (
                reference.document_kind == "ORDER"
                and reference.external_id
                and _is_primary_letter_reference(reference)
            ):
                _add_relation_candidate(
                    candidates,
                    seen,
                    own_external_id,
                    reference.external_id,
                    RelationType.RELATED_TO,
                    reference,
                )
    return candidates


def _extract_amended_order_numbers(text: str) -> set[str]:
    numbers: set[str] = set()
    for match in re.finditer(
        r"внесення\s+змін\s+до\s+наказу\s+Міністерства\s+фінансів\s+України\s+"
        r"від\s+(?:\d{1,2}\.\d{1,2}\.\d{4}|\d{1,2}\s+[а-яіїєґ]+\s+\d{4}\s+року?)\s+"
        r"№\s*(?P<number>\d+)",
        text,
        flags=re.I,
    ):
        numbers.add(match.group("number"))
    return numbers


def _is_primary_letter_reference(reference: DpsDocumentReference) -> bool:
    return (
        reference.issuer == "MINFIN"
        and reference.date is not None
        and reference.date.year >= 2026
    )


def _parse_list_fragment(html: str, section_url: str) -> list[DpsDocumentStub]:
    parser = _ListItemExtractor()
    parser.feed(html)
    section_path = urlparse(section_url).path.rstrip("/") + "/"
    stubs: list[DpsDocumentStub] = []
    seen: set[str] = set()
    for href, title, surrounding_text in parser.items:
        absolute_url = urljoin(section_url, href)
        parsed_path = urlparse(absolute_url).path
        if section_path not in parsed_path:
            continue
        try:
            page_id = extract_page_id(absolute_url)
        except ValueError:
            continue
        if page_id in seen:
            continue
        seen.add(page_id)
        published = parse_list_item_date(surrounding_text)
        canonical_url = print_to_canonical_url(absolute_url)
        stubs.append(
            DpsDocumentStub(
                page_id=page_id,
                external_id=external_id(page_id),
                title=title,
                canonical_url=canonical_url,
                print_url=canonical_to_print_url(canonical_url),
                source_url=section_url,
                section=None,
                document_type=classify_document_type(canonical_url),
                published_at=published,
            )
        )
    return stubs


def parse_list_item_date(text: str) -> datetime | None:
    match = re.search(r"(\d{1,2}\s+[а-яіїєґ]+\s+\d{4})", text, flags=re.I)
    if not match:
        return None
    parsed = parse_source_date(match.group(1))
    if parsed is None:
        return None
    return datetime.combine(parsed, time.min, tzinfo=timezone.utc)


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    text = parser.text()
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def _add_relation_candidate(
    candidates: list[DpsRelationCandidate],
    seen: set[tuple[str, str, RelationType]],
    from_external_id: str,
    to_external_id: str,
    relation_type: RelationType,
    reference: DpsDocumentReference,
) -> None:
    key = (from_external_id, to_external_id, relation_type)
    if key in seen:
        return
    seen.add(key)
    candidates.append(
        DpsRelationCandidate(
            from_external_id=from_external_id,
            to_external_id=to_external_id,
            relation_type=relation_type,
            metadata={
                "explicit": True,
                "deterministic": True,
                "evidence": "strict reference",
                "reference": reference.model_dump(mode="json"),
            },
        )
    )


def _resolve_reference(
    reference_index: dict[tuple[str, str], str] | None,
    kind: str,
    number: str,
) -> str | None:
    if reference_index is None:
        return None
    return reference_index.get((kind, number))


def _extract_footer_canonical_url(html: str) -> str | None:
    urls = re.findall(r"https?://(?:www\.)?tax\.gov\.ua/[^\s<]+?\.html", html)
    canonical_urls = [url for url in urls if "/print-" not in url]
    return canonical_urls[-1] if canonical_urls else None


def _extract_print_container(html: str) -> str:
    return _extract_class_container(html, "print") or html


def _extract_class_container(html: str, class_name: str) -> str | None:
    match = re.search(
        rf'<div[^>]+class=["\'][^"\']*\b{re.escape(class_name)}\b[^"\']*["\'][^>]*>',
        html,
        flags=re.I,
    )
    if not match:
        return None
    start = match.start()
    depth = 0
    for tag in re.finditer(r"</?div\b[^>]*>", html[start:], flags=re.I):
        token = tag.group(0)
        if token.startswith("</"):
            depth -= 1
            if depth == 0:
                return html[start : start + tag.end()]
        else:
            depth += 1
    return html[start:]


def _remove_scripts_and_styles(html: str) -> str:
    html = re.sub(r"<script\b.*?</script>", " ", html, flags=re.I | re.S)
    html = re.sub(r"<style\b.*?</style>", " ", html, flags=re.I | re.S)
    html = re.sub(r"<!--.*?-->", " ", html, flags=re.S)
    return html


def _extract_title(html: str, text: str) -> str:
    title = _first_match(r"<title[^>]*>(.*?)</title>", html, flags=re.I | re.S)
    if title:
        title = _clean_text(title)
    if not title or title.lower() in {"access denied", "головна сторінка державної податкової служби україни"}:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        title = lines[0] if lines else ""
    if not title:
        raise ValueError("DPS page is missing title")
    return title


def _extract_author(text: str) -> str | None:
    match = re.search(r"\n(?P<author>[^\n,]{3,120})\s*,\s*опубліковано", text, flags=re.I)
    if match:
        return _clean_text(match.group("author"))
    return None


def _extract_body_text(text: str) -> str:
    body = re.sub(r"^.*?Розділ:\s*[^\n]+", "", text, count=1, flags=re.S)
    body = re.sub(r"©\s*\d{4}\s+Державна податкова служба України.*$", "", body, flags=re.S)
    body = re.sub(r"https?://(?:www\.)?tax\.gov\.ua/\S+\.html\s*$", "", body)
    body = body.strip()
    if not body:
        body = text.strip()
    if len(body) < 20:
        raise ValueError("DPS page body is missing or too short")
    return body


def _extract_effective_at(text: str) -> datetime | None:
    match = re.search(r"З\s+(\d{1,2}\s+[а-яіїєґ]+\s+\d{4})\s+року", text, flags=re.I)
    if not match:
        return None
    parsed = parse_source_date(match.group(1))
    if parsed is None:
        return None
    return datetime.combine(parsed, time.min, tzinfo=timezone.utc)


def _first_match(pattern: str, text: str, flags: int = re.I) -> str | None:
    match = re.search(pattern, text, flags=flags)
    if not match:
        return None
    return _clean_text(match.group(1))


def _clean_text(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _date_or_none(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        logger.warning("dps_date_parse_failed year=%s month=%s day=%s", year, month, day)
        return None


class _TextExtractor(HTMLParser):
    block_tags = {"p", "div", "tr", "table", "h1", "h2", "h3", "h4", "h5", "li", "br"}
    skip_tags = {"script", "style", "noscript", "img"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.skip_tags:
            self._skip_depth += 1
        if tag in self.block_tags:
            self._append_newline()

    def handle_endtag(self, tag: str) -> None:
        if tag in self.skip_tags and self._skip_depth:
            self._skip_depth -= 1
        if tag in self.block_tags:
            self._append_newline()

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            cleaned = re.sub(r"[ \t\r\n\f\v]+", " ", unescape(data)).strip()
            if cleaned:
                self._chunks.append(cleaned)
                self._chunks.append(" ")

    def text(self) -> str:
        return "".join(self._chunks).strip()

    def _append_newline(self) -> None:
        if self._chunks and self._chunks[-1] != "\n":
            self._chunks.append("\n")


class _LinkExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._current_href: str | None = None
        self._current_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            attrs_dict = dict(attrs)
            self._current_href = attrs_dict.get("href")
            self._current_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._current_href:
            self.links.append((self._current_href, _clean_text(" ".join(self._current_text))))
            self._current_href = None
            self._current_text = []

    def handle_data(self, data: str) -> None:
        if self._current_href:
            self._current_text.append(data)


class _ListItemExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: list[tuple[str, str, str]] = []
        self._href: str | None = None
        self._anchor_text: list[str] = []
        self._recent_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            href = dict(attrs).get("href")
            if href and PAGE_ID_RE.search(href):
                self._href = href
                self._anchor_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href:
            title = _clean_text(" ".join(self._anchor_text))
            if title:
                self.items.append((self._href, title, " ".join(self._recent_text[-20:])))
            self._href = None
            self._anchor_text = []

    def handle_data(self, data: str) -> None:
        text = _clean_text(data)
        if text:
            self._recent_text.append(text)
        if self._href:
            self._anchor_text.append(data)
