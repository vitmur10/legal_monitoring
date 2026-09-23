from __future__ import annotations

import logging
import re
from datetime import date, datetime, time, timezone
from html import unescape
from html.parser import HTMLParser
from pathlib import PurePosixPath
from urllib.parse import unquote, urljoin, urlparse, urlunparse

from app.sources.minfin.client import normalize_url
from app.sources.minfin.schemas import (
    MinfinAttachment,
    MinfinConsultationStub,
    MinfinDocumentReference,
    MinfinDocumentStub,
    MinfinDocumentType,
    MinfinOrderStub,
    MinfinParsedPage,
)

logger = logging.getLogger(__name__)

BASE_URL = "https://mof.gov.ua"
ATTACHMENT_RE = re.compile(r"\.(?P<extension>pdf|docx?|xlsx?|xls|zip|xml)(?:$|[?#])", re.I)
NUMERIC_SUFFIX_RE = re.compile(r"-(?P<id>\d+)\.?$")
NEWS_RE = re.compile(r"^/uk/news/(?:.+-)?(?P<id>\d+)/?$", re.I)
ORDER_REF_RE = re.compile(
    r"(?P<text>(?:наказ(?:ом|у)?\s+)?"
    r"(?:Міністерства\s+фінансів\s+України|Мінфіну)\s+від\s+"
    r"(?P<date>\d{1,2}\.\d{1,2}\.\d{4}|\d{1,2}\s+[а-яіїєґ]+\s+\d{4}(?:\s+року)?)\s+"
    r"№\s*(?P<number>\d+))",
    re.I,
)
TAX_CODE_RE = re.compile(
    r"(?:(?:пункт|пункту|підпункт|підпунктами|стаття|статті|розділ|розділу|підрозділ|підрозділу)"
    r"[^.;:\n]{0,120}?(?:Податкового\s+кодексу\s+України|Кодексу))",
    re.I,
)
EFFECTIVE_DATE_RE = re.compile(
    r"(?:з|із|від)\s+(?P<date>\d{1,2}\s+[а-яіїєґ]+\s+\d{4})(?:\s+року)?",
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


def canonical_url(url: str) -> str:
    parsed = urlparse(normalize_url(url))
    path = _normalize_path(parsed.path)
    return urlunparse(("https", "mof.gov.ua", path, "", parsed.query, ""))


def external_id_from_url(url: str) -> str:
    parsed = urlparse(canonical_url(url))
    path = _normalize_path(parsed.path)
    news = NEWS_RE.match(path)
    if news:
        return f"news:{news.group('id')}"
    suffix = NUMERIC_SUFFIX_RE.search(path.rstrip("/"))
    if suffix:
        return f"page:{suffix.group('id')}"
    return f"path:{path.rstrip('/') or '/'}"


def order_external_id(order_date: date, order_number: str) -> str:
    return f"order:{order_date.isoformat()}:{order_number}"


def consultation_external_id(order_date: date, order_number: str) -> str:
    return f"general_tax_consultation:{order_date.isoformat()}:{order_number}"


def classify_document_type(url: str, section: str | None = None, row_type: str | None = None) -> MinfinDocumentType:
    text = f"{url} {section or ''} {row_type or ''}".lower()
    if row_type == "consultation" or "set-of-summarizing-tax-consultations" in text:
        return MinfinDocumentType.GENERAL_TAX_CONSULTATION
    if row_type == "order" or "orders_of_the_ministry_of_finance" in text.lower():
        return MinfinDocumentType.ORDER
    if "/uk/news" in text:
        return MinfinDocumentType.NEWS
    if "crs" in text or "clarification-641" in text:
        return MinfinDocumentType.CRS
    if "tax-policy" in text:
        return MinfinDocumentType.TAX_POLICY
    if "financial" in text or "fin-zvitnosti" in text:
        return MinfinDocumentType.FINANCIAL_REPORTING
    if (
        "accounting" in text
        or "nacionalni-polozhennja" in text
        or "roz_jasnennja" in text
        or "роз'яснення з бухгалтерського" in text
        or "бухгалтер" in text
    ):
        return MinfinDocumentType.ACCOUNTING
    return MinfinDocumentType.OTHER


def parse_source_date(value: str | None) -> date | None:
    if not value:
        return None
    text = re.sub(r"\s+", " ", unescape(value).lower().replace("року", "")).strip()
    numeric = re.fullmatch(r"(?P<day>\d{1,2})[./](?P<month>\d{1,2})[./](?P<year>\d{4})", text)
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


def date_to_datetime(value: date | None) -> datetime | None:
    if value is None:
        return None
    return datetime.combine(value, time.min, tzinfo=timezone.utc)


def parse_page(html: str, source_url: str) -> MinfinParsedPage:
    canonical = canonical_url(source_url)
    doc_type = classify_document_type(canonical)
    tree = _TreeBuilder()
    tree.feed(_strip_scripts_styles(html))
    root = tree.root
    content = _select_main_content(root)
    title = _extract_h1(content) or _extract_h1(root) or _extract_title(html)
    if not title:
        raise ValueError(f"Minfin page is missing title: {source_url}")
    body = _semantic_text(content)
    if len(body) < 10:
        raise ValueError(f"Minfin page body is missing or too short: {source_url}")
    attachments = parse_attachments_from_node(content, canonical, source_context=external_id_from_url(canonical))
    references = parse_document_references(f"{title}\n{body}")
    references.extend(parse_rada_references_from_node(content, canonical))
    references = _dedupe_references(references)
    effective_at = _extract_effective_at(body)
    published_at = _extract_news_published_at(body) if doc_type == MinfinDocumentType.NEWS else None
    return MinfinParsedPage(
        external_id=external_id_from_url(canonical),
        title=title,
        canonical_url=canonical,
        source_url=source_url,
        document_type=doc_type,
        body=body,
        published_at=published_at,
        effective_at=effective_at,
        attachments=attachments,
        references=references,
    )


def parse_news_list(html: str, source_url: str) -> list[MinfinDocumentStub]:
    tree = _TreeBuilder()
    tree.feed(_strip_scripts_styles(html))
    stubs: list[MinfinDocumentStub] = []
    seen: set[str] = set()
    for href, label, context in _links_with_context(tree.root):
        absolute = canonical_url(urljoin(source_url, href))
        if not NEWS_RE.match(urlparse(absolute).path):
            continue
        ext_id = external_id_from_url(absolute)
        if ext_id in seen:
            continue
        seen.add(ext_id)
        published = date_to_datetime(_extract_first_date(context))
        stubs.append(
            MinfinDocumentStub(
                external_id=ext_id,
                title=label,
                source_url=source_url,
                canonical_url=absolute,
                document_type=MinfinDocumentType.NEWS,
                published_at=published,
            )
        )
    return stubs


def parse_order_table(html: str, source_url: str) -> list[MinfinOrderStub]:
    return _parse_legal_rows(html, source_url, row_type="order")


def parse_consultation_table(html: str, source_url: str) -> list[MinfinConsultationStub]:
    rows = _parse_legal_rows(html, source_url, row_type="consultation")
    consultations: list[MinfinConsultationStub] = []
    for row in rows:
        consultations.append(
            MinfinConsultationStub(
                external_id=consultation_external_id(row.order_date, row.order_number),
                row_date=row.row_date,
                order_date=row.order_date,
                order_number=row.order_number,
                title=row.title,
                source_url=row.source_url,
                canonical_url=row.canonical_url,
                attachments=row.attachments,
                references=row.references,
                tax_code_references=parse_tax_code_references(row.title),
            )
        )
    return consultations


def parse_attachments(html: str, page_url: str, source_context: str) -> list[MinfinAttachment]:
    tree = _TreeBuilder()
    tree.feed(_strip_scripts_styles(html))
    return parse_attachments_from_node(tree.root, page_url, source_context)


def parse_attachments_from_node(node: "_Node", page_url: str, source_context: str) -> list[MinfinAttachment]:
    attachments: list[MinfinAttachment] = []
    seen: set[str] = set()
    for href, label, _context in _links_with_context(node):
        absolute = canonical_url(urljoin(page_url, href))
        match = ATTACHMENT_RE.search(absolute)
        if not match or absolute in seen:
            continue
        seen.add(absolute)
        attachments.append(
            MinfinAttachment(
                label=label or _filename_label(absolute),
                url=absolute,
                extension=match.group("extension").lower(),
                source_context=source_context,
            )
        )
    return attachments


def parse_document_references(text: str) -> list[MinfinDocumentReference]:
    references: list[MinfinDocumentReference] = []
    seen: set[tuple[str, str | None, str | None, str | None]] = set()
    for match in ORDER_REF_RE.finditer(text):
        ref_date = parse_source_date(match.group("date"))
        number = match.group("number")
        key = ("MINFIN_ORDER", number, ref_date.isoformat() if ref_date else None, None)
        if key in seen:
            continue
        seen.add(key)
        references.append(
            MinfinDocumentReference(
                kind="MINFIN_ORDER",
                number=number,
                date=ref_date,
                text=_clean_text(match.group("text")),
            )
        )
    return references


def parse_rada_references_from_node(node: "_Node", page_url: str) -> list[MinfinDocumentReference]:
    references: list[MinfinDocumentReference] = []
    seen: set[str] = set()
    for href, label, _context in _links_with_context(node):
        absolute = urljoin(page_url, href)
        host = urlparse(absolute).netloc.lower()
        if host not in {"zakon.rada.gov.ua", "zakon2.rada.gov.ua"}:
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        references.append(
            MinfinDocumentReference(
                kind="RADA_DOCUMENT",
                url=absolute,
                text=label or absolute,
            )
        )
    return references


def parse_tax_code_references(text: str) -> list[str]:
    seen: set[str] = set()
    results: list[str] = []
    for match in TAX_CODE_RE.finditer(text):
        value = _clean_text(match.group(0))
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        results.append(value)
    return results


def semantic_content(
    *,
    title: str,
    body: str,
    row_date: date | None = None,
    order_date: date | None = None,
    order_number: str | None = None,
    attachments: list[MinfinAttachment] | None = None,
    references: list[MinfinDocumentReference] | None = None,
    tax_code_references: list[str] | None = None,
) -> str:
    parts = [f"Title: {title}", "", body]
    if row_date:
        parts.extend(["", f"Row date: {row_date.isoformat()}"])
    if order_date:
        parts.append(f"Order date: {order_date.isoformat()}")
    if order_number:
        parts.append(f"Order number: {order_number}")
    if tax_code_references:
        parts.append("Tax Code references:")
        parts.extend(f"- {item}" for item in tax_code_references)
    if attachments:
        parts.append("Attachments:")
        for attachment in attachments:
            parts.append(f"- {attachment.label} | {attachment.url} | {attachment.extension}")
    if references:
        parts.append("References:")
        for reference in references:
            date_text = reference.date.isoformat() if reference.date else ""
            parts.append(f"- {reference.kind} | {reference.number or ''} | {date_text} | {reference.url or ''} | {reference.text}")
    return "\n".join(parts)


def _parse_legal_rows(html: str, source_url: str, row_type: str) -> list[MinfinOrderStub]:
    tree = _TreeBuilder()
    tree.feed(_strip_scripts_styles(html))
    rows: list[MinfinOrderStub] = []
    for tr in _iter_nodes(tree.root, "tr"):
        cells = [_semantic_text(cell) for cell in tr.children if cell.tag in {"td", "th"}]
        row_text = _semantic_text(tr)
        if len(cells) < 2 or "№" not in row_text:
            continue
        match = ORDER_REF_RE.search(row_text)
        if not match:
            continue
        order_date_value = parse_source_date(match.group("date"))
        if order_date_value is None:
            continue
        order_number = match.group("number")
        row_date = _extract_first_date(cells[0])
        title = _clean_text(match.group("text"))
        if len(cells) > 1:
            title = max((_clean_text(cell) for cell in cells[1:]), key=len, default=title)
        doc_type = classify_document_type(source_url, row_text, row_type=row_type)
        if doc_type == MinfinDocumentType.ORDER and _looks_accounting_title(title):
            doc_type = MinfinDocumentType.ACCOUNTING
        external = order_external_id(order_date_value, order_number)
        attachments = parse_attachments_from_node(tr, source_url, source_context=f"{row_type} row {external}")
        references = parse_document_references(row_text)
        rows.append(
            MinfinOrderStub(
                external_id=external,
                row_date=row_date,
                order_date=order_date_value,
                order_number=order_number,
                title=title,
                source_url=source_url,
                canonical_url=f"{canonical_url(source_url)}#{external}",
                attachments=attachments,
                references=references,
                document_type=doc_type,
            )
        )
    return _dedupe_rows(rows)


def _dedupe_rows(rows: list[MinfinOrderStub]) -> list[MinfinOrderStub]:
    seen: set[str] = set()
    result: list[MinfinOrderStub] = []
    for row in rows:
        if row.external_id in seen:
            continue
        seen.add(row.external_id)
        result.append(row)
    return result


def _select_main_content(root: "_Node") -> "_Node":
    _remove_global_nodes(root)
    h1 = next(_iter_nodes(root, "h1"), None)
    if h1 is None:
        return _largest_content_node(root)
    node = h1.parent
    while node and node.parent and node.parent.tag not in {"html", "body", "document"}:
        if _content_score(node) >= 8:
            return node
        node = node.parent
    return h1.parent or root


def _remove_global_nodes(node: "_Node") -> None:
    kept = []
    for child in node.children:
        attrs_text = " ".join(str(value) for value in child.attrs.values()).lower()
        if child.tag in {"script", "style", "noscript", "header", "footer", "nav", "form"}:
            continue
        if any(token in attrs_text for token in ("search", "newsletter", "subscribe", "social", "footer", "header", "menu", "breadcrumbs", "related")):
            continue
        _remove_global_nodes(child)
        kept.append(child)
    node.children = kept


def _largest_content_node(root: "_Node") -> "_Node":
    candidates = [node for node in _iter_nodes(root) if node.tag in {"main", "article", "section", "div", "body"}]
    return max(candidates or [root], key=_content_score)


def _content_score(node: "_Node") -> int:
    allowed_count = sum(1 for item in _iter_nodes(node) if item.tag in {"p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "table", "tr", "a"})
    return allowed_count + min(len(_text(node)) // 100, 20)


def _extract_h1(node: "_Node") -> str | None:
    h1 = next(_iter_nodes(node, "h1"), None)
    return _clean_text(_text(h1)) if h1 else None


def _extract_title(html: str) -> str | None:
    match = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.I | re.S)
    return _clean_text(match.group(1)) if match else None


def _semantic_text(node: "_Node") -> str:
    chunks: list[str] = []
    _collect_semantic_text(node, chunks)
    text = "".join(chunks)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def _collect_semantic_text(node: "_Node", chunks: list[str]) -> None:
    allowed = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "table", "tr", "td", "th", "a", "br", "div", "section", "article", "main", "body", "document"}
    if node.tag not in allowed:
        return
    if node.tag in {"p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr", "table"}:
        _append_newline(chunks)
    if node.text:
        chunks.append(_clean_inline(node.text))
        chunks.append(" ")
    for child in node.children:
        _collect_semantic_text(child, chunks)
        if child.tail:
            chunks.append(_clean_inline(child.tail))
            chunks.append(" ")
    if node.tag in {"p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr", "table"}:
        _append_newline(chunks)


def _links_with_context(node: "_Node") -> list[tuple[str, str, str]]:
    links = []
    for link in _iter_nodes(node, "a"):
        href = link.attrs.get("href")
        if not href:
            continue
        context_node = link.parent or node
        links.append((href, _clean_text(_text(link)), _semantic_text(context_node)))
    return links


def _iter_nodes(node: "_Node", tag: str | None = None):
    if tag is None or node.tag == tag:
        yield node
    for child in node.children:
        yield from _iter_nodes(child, tag)


def _text(node: "_Node" | None) -> str:
    if node is None:
        return ""
    chunks = [node.text]
    for child in node.children:
        chunks.append(_text(child))
        chunks.append(child.tail)
    return " ".join(part for part in chunks if part)


def _dedupe_references(references: list[MinfinDocumentReference]) -> list[MinfinDocumentReference]:
    seen: set[tuple[str, str | None, str | None, str | None]] = set()
    result: list[MinfinDocumentReference] = []
    for reference in references:
        key = (
            reference.kind,
            reference.number,
            reference.date.isoformat() if reference.date else None,
            reference.url,
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(reference)
    return result


def _extract_effective_at(text: str) -> datetime | None:
    candidates: list[datetime] = []
    for match in EFFECTIVE_DATE_RE.finditer(text):
        if "чин" not in text[max(0, match.start() - 80) : match.end() + 80].lower() and "застос" not in text[max(0, match.start() - 80) : match.end() + 80].lower():
            continue
        parsed = parse_source_date(match.group("date"))
        if parsed:
            candidates.append(date_to_datetime(parsed))
    return candidates[-1] if candidates else None


def _extract_news_published_at(text: str) -> datetime | None:
    return date_to_datetime(_extract_first_date(text[:300]))


def _extract_first_date(text: str) -> date | None:
    match = re.search(r"\d{1,2}[./]\d{1,2}[./]\d{4}|\d{1,2}\s+[а-яіїєґ]+\s+\d{4}", text, flags=re.I)
    return parse_source_date(match.group(0)) if match else None


def _looks_accounting_title(title: str) -> bool:
    lower = title.lower()
    return "бухгалтер" in lower or "фінансов" in lower or "нп(с)бо" in lower or "положення (стандарт" in lower


def _normalize_path(path: str) -> str:
    normalized = "/" + str(PurePosixPath(unquote(path))).lstrip("/")
    if normalized != "/" and normalized.endswith("/"):
        normalized = normalized.rstrip("/")
    return normalized


def _filename_label(url: str) -> str:
    return unquote(PurePosixPath(urlparse(url).path).name)


def _strip_scripts_styles(html: str) -> str:
    html = re.sub(r"<script\b.*?</script>", " ", html, flags=re.I | re.S)
    html = re.sub(r"<style\b.*?</style>", " ", html, flags=re.I | re.S)
    html = re.sub(r"<!--.*?-->", " ", html, flags=re.S)
    return html


def _clean_text(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _clean_inline(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(value)).strip()


def _append_newline(chunks: list[str]) -> None:
    if chunks and chunks[-1] != "\n":
        chunks.append("\n")


def _date_or_none(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        logger.warning("minfin_date_parse_failed year=%s month=%s day=%s", year, month, day)
        return None


class _Node:
    def __init__(self, tag: str, attrs: dict[str, str], parent: "_Node | None" = None) -> None:
        self.tag = tag
        self.attrs = attrs
        self.parent = parent
        self.children: list[_Node] = []
        self.text = ""
        self.tail = ""


class _TreeBuilder(HTMLParser):
    void_tags = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("document", {})
        self.stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = _Node(tag.lower(), {key.lower(): value or "" for key, value in attrs}, self.stack[-1])
        self.stack[-1].children.append(node)
        if node.tag not in self.void_tags:
            self.stack.append(node)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data: str) -> None:
        if not self.stack:
            return
        current = self.stack[-1]
        if current.children:
            current.children[-1].tail += data
        else:
            current.text += data
