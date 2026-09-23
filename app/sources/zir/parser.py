from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from html import unescape
from html.parser import HTMLParser
from urllib.parse import parse_qs, urljoin, urlparse

from app.sources.zir.schemas import (
    ZirAnswer,
    ZirCategory,
    ZirConsultation,
    ZirConsultationStub,
    ZirNormativeReference,
    ZirSearchResult,
    ZirStatus,
)

BASE_URL = "https://zir.tax.gov.ua"
SUPPORTED_SRC = "ques"


def external_id(src: str, zir_id: str) -> str:
    return f"{src}:{zir_id}"


def canonical_url(src: str, zir_id: str) -> str:
    return f"{BASE_URL}/main/bz/view/?src={src}&id={zir_id}"


def parse_external_id(value: str) -> tuple[str, str]:
    match = re.fullmatch(r"(?P<src>[a-z]+):(?P<id>\d+)", value)
    if not match:
        raise ValueError(f"Invalid ZIR external_id: {value}")
    return match.group("src"), match.group("id")


def extract_id_from_url(url: str) -> tuple[str, str]:
    query = parse_qs(urlparse(url).query)
    src = (query.get("src") or [SUPPORTED_SRC])[0]
    zir_id = (query.get("id") or [""])[0]
    if not zir_id:
        raise ValueError(f"ZIR URL does not contain id: {url}")
    return src, zir_id


def validate_ajax_xml(text: str, required_tags: tuple[str, ...]) -> ET.Element:
    leading = text.lstrip()[:200].lower()
    if leading.startswith("<!doctype html") or leading.startswith("<html"):
        raise ValueError("ZIR returned a full HTML page instead of AJAX XML")
    if "module\\defaults\\erroor.phtml" in text or "<title>Помилка</title>" in text:
        raise ValueError("ZIR returned an HTML error page with HTTP 200")
    try:
        root = ET.fromstring(text.strip())
    except ET.ParseError as exc:
        raise ValueError("ZIR AJAX response is not valid XML-like payload") from exc
    if root.tag != "body":
        raise ValueError(f"Unexpected ZIR AJAX root tag: {root.tag}")
    for tag in required_tags:
        if root.find(tag) is None:
            raise ValueError(f"ZIR AJAX response is missing <{tag}>")
    return root


def parse_search_response(text: str, default_status: ZirStatus = ZirStatus.UNKNOWN) -> ZirSearchResult:
    root = validate_ajax_xml(text, ("count", "content"))
    count_text = (root.findtext("count") or "").strip()
    count = int(count_text) if count_text.isdigit() else None
    content = unescape(root.findtext("content") or "")
    return ZirSearchResult(count=count, items=parse_search_content(content, default_status))


def parse_load_more_response(text: str, default_status: ZirStatus = ZirStatus.UNKNOWN) -> ZirSearchResult:
    root = validate_ajax_xml(text, ("content",))
    content = unescape(root.findtext("content") or "")
    return ZirSearchResult(count=None, items=parse_search_content(content, default_status))


def parse_search_content(html: str, default_status: ZirStatus = ZirStatus.UNKNOWN) -> list[ZirConsultationStub]:
    rows = _result_rows(html)
    items: list[ZirConsultationStub] = []
    seen: set[str] = set()
    for row in rows:
        link = _first_match(r'<a\b[^>]*href=["\'](?P<href>[^"\']+)["\'][^>]*>(?P<html>.*?)</a>', row)
        if not link:
            continue
        href = unescape(link.group("href"))
        try:
            src, zir_id = extract_id_from_url(href)
        except ValueError:
            zir_id = _extract_row_id(row)
            src = SUPPORTED_SRC
        if not zir_id or src != SUPPORTED_SRC or zir_id in seen:
            continue
        seen.add(zir_id)
        question = html_to_text(link.group("html"))
        if not question:
            continue
        category = _extract_category(row)
        status_text = _extract_status_text(row)
        status = detect_status(f"{status_text or ''}\n{question}", default=default_status)
        items.append(
            ZirConsultationStub(
                id=zir_id,
                external_id=external_id(src, zir_id),
                question=question,
                category=category,
                status=status,
                status_text=status_text,
                canonical_url=canonical_url(src, zir_id),
                src=src,
            )
        )
    return items


def parse_category_path(html: str, parent_id: str | None = None) -> list[ZirCategory]:
    parser = _SelectOptionExtractor()
    parser.feed(html)
    categories: list[ZirCategory] = []
    selected_parent = parent_id
    for select_index, options in enumerate(parser.selects):
        current_parent = None if select_index == 0 else selected_parent
        for value, label, disabled in options:
            if disabled or value in {"", "0", "-1"}:
                continue
            categories.append(_category_from_option(value, label, current_parent))
        selected = next((value for value, _label, disabled in options if not disabled and value not in {"", "0", "-1"}), None)
        if select_index == 0 and selected:
            selected_parent = selected
    return categories


def parse_answer_fragment(html: str) -> ZirAnswer:
    fragment = html.split("<br />[", 1)[0]
    text = html_to_text(fragment)
    short_answer, full_answer = split_answer(text)
    comments = extract_comments(text)
    return ZirAnswer(
        short_answer=short_answer,
        full_answer=full_answer,
        comments=comments,
        raw_text=text,
    )


def parse_consultation_page(
    html: str,
    url: str,
    fallback_stub: ZirConsultationStub | None = None,
) -> ZirConsultation:
    src, zir_id = extract_id_from_url(url)
    if src != SUPPORTED_SRC:
        raise ValueError(f"Unsupported ZIR src: {src}")

    question = _extract_fieldset_text(html, "Питання") or _input_value(html, "expQues")
    answer_html = _extract_fieldset_html(html, "Відповідь")
    answer = parse_answer_fragment(answer_html or _input_value(html, "expAnsw") or "")
    if not question and fallback_stub:
        question = fallback_stub.question
    if not question:
        raise ValueError(f"ZIR consultation {zir_id} is missing question")

    category = fallback_stub.category if fallback_stub else _extract_category(html)
    status_text = _extract_status_text(html)
    combined = "\n".join(
        part
        for part in [
            status_text,
            question,
            answer.raw_text,
            " ".join(answer.comments),
            fallback_stub.status_text if fallback_stub else None,
        ]
        if part
    )
    status = detect_status(combined, default=fallback_stub.status if fallback_stub else ZirStatus.UNKNOWN)
    references = extract_normative_references(f"{question}\n{answer.raw_text}\n{' '.join(answer.comments)}")

    return ZirConsultation(
        id=zir_id,
        external_id=external_id(src, zir_id),
        canonical_url=canonical_url(src, zir_id),
        src=src,
        question=clean_text(question),
        short_answer=answer.short_answer,
        full_answer=answer.full_answer,
        status=status,
        status_text=status_text or (fallback_stub.status_text if fallback_stub else None),
        category=category,
        comments=answer.comments,
        normative_references=references,
    )


def split_answer(text: str) -> tuple[str | None, str | None]:
    cleaned = clean_text(text)
    short_match = re.search(
        r"(?:^|\s)Коротка:\s*(?P<short>.*?)(?:\s+Повна:\s*(?P<full>.*)|$)",
        cleaned,
        flags=re.I | re.S,
    )
    if short_match:
        short_answer = clean_text(short_match.group("short"))
        full_raw = short_match.group("full")
        return short_answer or None, clean_text(full_raw) if full_raw else None
    identical = re.sub(r"^Коротка\s+та\s+повна\s+відповіді\s+ідентичні\.\s*", "", cleaned, flags=re.I)
    return None, identical or cleaned or None


def detect_status(text: str, default: ZirStatus = ZirStatus.UNKNOWN) -> ZirStatus:
    normalized = text.lower()
    non_current_patterns = (
        "втратила чинність",
        "втратило чинність",
        "діяло до",
        "діяла до",
        "переведено до нечинних",
    )
    if any(pattern in normalized for pattern in non_current_patterns):
        return ZirStatus.NON_CURRENT
    current_patterns = ("чинна", "чинні")
    if default == ZirStatus.CURRENT or any(pattern in normalized for pattern in current_patterns):
        return ZirStatus.CURRENT
    return default


def extract_comments(text: str) -> list[str]:
    comments = []
    for match in re.finditer(r"Коментар:\s*(?P<comment>.+?)(?=(?:\s+Коментар:)|$)", text, flags=re.I | re.S):
        comments.append(clean_text(match.group("comment")).strip(" «»\""))
    return comments


def extract_validity_text(text: str) -> str | None:
    match = re.search(r"(Діял[ао]\s+до\s+\d{1,2}\.\d{1,2}\.\d{4})", text, flags=re.I)
    return clean_text(match.group(1)) if match else None


def extract_normative_references(text: str) -> list[ZirNormativeReference]:
    references: list[ZirNormativeReference] = []
    seen: set[tuple[str, str | None, str | None, str | None]] = set()

    for match in re.finditer(r"п\.\s*(?P<paragraph>\d+(?:\.\d+)*)\s+ст\.\s*(?P<article>\d+)", text, flags=re.I):
        ref = ZirNormativeReference(
            reference_type="TAX_CODE_PARAGRAPH",
            article=match.group("article"),
            paragraph=match.group("paragraph"),
            text=clean_text(match.group(0)),
        )
        _append_reference(references, seen, ref)

    for match in re.finditer(r"№\s*(?P<number>2755-[A-ZА-ЯІЇЄҐVІX]+)", text, flags=re.I):
        ref = ZirNormativeReference(
            reference_type="TAX_CODE",
            number=match.group("number"),
            text=clean_text(match.group(0)),
        )
        _append_reference(references, seen, ref)

    for match in re.finditer(
        r"(?:Закон(?:ом)?\s+України(?:\s+від\s+\d{1,2}\s+[а-яіїєґ]+\s+\d{4}\s+року)?\s+№\s*(?P<number>\d+-[A-ZА-ЯІЇЄҐVІX]+))",
        text,
        flags=re.I,
    ):
        ref = ZirNormativeReference(
            reference_type="LAW",
            number=match.group("number"),
            text=clean_text(match.group(0)),
        )
        _append_reference(references, seen, ref)

    if re.search(r"\bПКУ\b|Податкового\s+кодексу\s+України", text, flags=re.I):
        ref = ZirNormativeReference(reference_type="TAX_CODE", text="ПКУ / Податковий кодекс України")
        _append_reference(references, seen, ref)

    return references


def semantic_content(consultation: ZirConsultation) -> str:
    parts = [
        f"Question: {consultation.question}",
        f"Short answer: {consultation.short_answer or ''}",
        f"Full answer: {consultation.full_answer or ''}",
        f"Status: {consultation.status.value}",
        f"Validity: {extract_validity_text(' '.join([consultation.question, consultation.short_answer or '', consultation.full_answer or ''])) or ''}",
        f"Comments: {' | '.join(consultation.comments)}",
    ]
    return "\n".join(clean_text(part) for part in parts)


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(unescape(html))
    return clean_text(parser.text())


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    text = unescape(value)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _append_reference(
    references: list[ZirNormativeReference],
    seen: set[tuple[str, str | None, str | None, str | None]],
    ref: ZirNormativeReference,
) -> None:
    key = (ref.reference_type, ref.number, ref.article, ref.paragraph)
    if key in seen:
        return
    seen.add(key)
    references.append(ref)


def _result_rows(html: str) -> list[str]:
    starts = [match.start() for match in re.finditer(r'<div\b[^>]*id=["\']result_row["\'][^>]*>', html, flags=re.I)]
    if not starts:
        return []
    rows = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(html)
        rows.append(html[start:end])
    return rows


def _extract_row_id(row: str) -> str:
    for pattern in (
        r'row-id=["\'](?P<id>\d+)["\']',
        r'quesid=["\'](?P<id>\d+)["\']',
        r'quesid=(?P<id>\d+)',
    ):
        match = re.search(pattern, row, flags=re.I)
        if match:
            return match.group("id")
    return ""


def _extract_category(html: str) -> str | None:
    match = re.search(r'<div\b[^>]*id=["\']cat["\'][^>]*>(?P<html>.*?)</div>', html, flags=re.I | re.S)
    if not match:
        return None
    text = html_to_text(match.group("html"))
    text = re.sub(r"^Категорія:\s*", "", text, flags=re.I)
    return text or None


def _extract_status_text(html: str) -> str | None:
    match = re.search(r'<div\b[^>]*class=["\'][^"\']*\bactual\b[^"\']*["\'][^>]*>(?P<html>.*?)</div>', html, flags=re.I | re.S)
    return html_to_text(match.group("html")) if match else None


def _extract_fieldset_html(html: str, legend: str) -> str | None:
    pattern = (
        r'<fieldset\b[^>]*>\s*<legend\b[^>]*>\s*'
        + re.escape(legend)
        + r"\s*</legend>(?P<html>.*?)</fieldset>"
    )
    match = re.search(pattern, html, flags=re.I | re.S)
    return match.group("html") if match else None


def _extract_fieldset_text(html: str, legend: str) -> str | None:
    fieldset = _extract_fieldset_html(html, legend)
    return html_to_text(fieldset) if fieldset else None


def _input_value(html: str, input_id: str) -> str | None:
    match = re.search(
        rf'<input\b[^>]*id=["\']{re.escape(input_id)}["\'][^>]*value=["\'](?P<value>.*?)["\']',
        html,
        flags=re.I | re.S,
    )
    return clean_text(match.group("value")) if match else None


def _category_from_option(value: str, label: str, parent_id: str | None) -> ZirCategory:
    raw = clean_text(label)
    match = re.match(r"(?P<code>\d+(?:\.\d+)*)\.?\s+(?P<title>.+)", raw)
    return ZirCategory(
        id=value,
        code=match.group("code") if match else None,
        title=match.group("title") if match else raw,
        parent_id=parent_id,
        raw_label=raw,
    )


def _first_match(pattern: str, text: str):
    return re.search(pattern, text, flags=re.I | re.S)


class _TextExtractor(HTMLParser):
    block_tags = {"p", "div", "tr", "table", "h1", "h2", "h3", "h4", "h5", "li", "br", "fieldset"}
    skip_tags = {"script", "style", "noscript", "img", "button", "nav"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.skip_tags:
            self._skip_depth += 1
        if tag in self.block_tags:
            self._append_space()

    def handle_endtag(self, tag: str) -> None:
        if tag in self.skip_tags and self._skip_depth:
            self._skip_depth -= 1
        if tag in self.block_tags:
            self._append_space()

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = clean_text(data)
        if text:
            self._chunks.append(text)
            self._chunks.append(" ")

    def text(self) -> str:
        return "".join(self._chunks)

    def _append_space(self) -> None:
        if self._chunks and self._chunks[-1] != " ":
            self._chunks.append(" ")


class _SelectOptionExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.selects: list[list[tuple[str, str, bool]]] = []
        self._in_select = False
        self._current_options: list[tuple[str, str, bool]] = []
        self._option_value: str | None = None
        self._option_disabled = False
        self._option_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        if tag == "select":
            self._in_select = True
            self._current_options = []
        elif self._in_select and tag == "option":
            self._option_value = attrs_dict.get("value") or ""
            self._option_disabled = "disabled" in attrs_dict
            self._option_text = []

    def handle_endtag(self, tag: str) -> None:
        if self._in_select and tag == "option" and self._option_value is not None:
            self._current_options.append(
                (self._option_value, clean_text(" ".join(self._option_text)), self._option_disabled)
            )
            self._option_value = None
            self._option_text = []
        elif tag == "select" and self._in_select:
            self.selects.append(self._current_options)
            self._current_options = []
            self._in_select = False

    def handle_data(self, data: str) -> None:
        if self._option_value is not None:
            self._option_text.append(data)
