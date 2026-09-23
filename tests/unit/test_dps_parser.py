from datetime import datetime, timezone

from app.models.enums import RelationType
from app.sources.dps.parser import (
    canonical_to_print_url,
    classify_document_type,
    extract_page_id,
    parse_attachments,
    parse_document_references,
    parse_list_page,
    parse_more_json,
    parse_print_page,
    parse_ukrainian_published_at,
)
from app.sources.dps.schemas import DpsDocumentType


def test_extract_page_id_from_canonical_and_print_urls() -> None:
    assert extract_page_id("https://tax.gov.ua/x/80085.html") == "80085"
    assert extract_page_id("https://tax.gov.ua/x/print-1025759.html") == "1025759"


def test_canonical_to_print_url() -> None:
    assert canonical_to_print_url("https://tax.gov.ua/x/80085.html") == (
        "https://tax.gov.ua/x/print-80085.html"
    )
    assert canonical_to_print_url("https://tax.gov.ua/x/print-80085.html") == (
        "https://tax.gov.ua/x/print-80085.html"
    )


def test_parse_ukrainian_published_at() -> None:
    assert parse_ukrainian_published_at("22 квітня 2026 о 16:30") == datetime(
        2026, 4, 22, 16, 30, tzinfo=timezone.utc
    )


def test_classify_document_type_from_path() -> None:
    assert classify_document_type("https://tax.gov.ua/media-tsentr/novini/1.html") == (
        DpsDocumentType.NEWS
    )
    assert classify_document_type("https://tax.gov.ua/zakonodavstvo/x/nakazi/1.html") == (
        DpsDocumentType.ORDER
    )
    assert classify_document_type("https://tax.gov.ua/zakonodavstvo/listi-dps/1.html") == (
        DpsDocumentType.LETTER
    )
    assert classify_document_type("https://tax.gov.ua/x/formi-zvitnosti/1.html") == (
        DpsDocumentType.REPORTING_FORM
    )


def test_parse_list_page_and_post_feed() -> None:
    section_url = "https://tax.gov.ua/media-tsentr/novini/"
    html = """
    <div class="news__item">
      <div class="shortnews__date">30 червня 2026</div>
      <a href="/media-tsentr/novini/1025759.html" class="news__title">CRS 2.0</a>
    </div>
    <a href="/unrelated/332465.html">Footer link</a>
    """

    [stub] = parse_list_page(html, section_url)
    assert stub.page_id == "1025759"
    assert stub.external_id == "dps:1025759"
    assert stub.print_url == "https://tax.gov.ua/media-tsentr/novini/print-1025759.html"
    assert stub.document_type == DpsDocumentType.NEWS
    assert stub.published_at.isoformat() == "2026-06-30T00:00:00+00:00"

    [feed_stub] = parse_more_json('{"feed": "' + html.replace('"', '\\"').replace("\n", "") + '"}', section_url)
    assert feed_stub.page_id == "1025759"


def test_parse_attachments_from_normal_page() -> None:
    html = """
    <div class="materials-additional">
      <ul>
        <li><a href="/data/normativ/000/005/80085/OSNOVNA_FORMA.docx">
          Податкова декларація (.docx, 50 Kb) (Завантажити)
        </a></li>
        <li><a href="/data/files/687542.pdf">Наказом (.pdf, 500 Kb)</a></li>
      </ul>
    </div>
    """

    attachments = parse_attachments(html, "https://tax.gov.ua/x/80085.html")

    assert [attachment.extension for attachment in attachments] == ["docx", "pdf"]
    assert attachments[0].url == "https://tax.gov.ua/data/normativ/000/005/80085/OSNOVNA_FORMA.docx"
    assert attachments[0].size_text == "50 Kb"


def test_parse_print_page_order_186_reference() -> None:
    page = parse_print_page(
        _print_html(
            page_id="80085",
            title=(
                "Наказ Міністерства фінансів України від 06.04.2026 № 186 "
                "«Про внесення змін до форми Податкової декларації з податку на прибуток підприємств»"
            ),
            author="Департамент методології",
            published="22 квітня 2026 о 16:30",
            section="Форми звітності",
            body="МІНІСТЕРСТВО ФІНАНСІВ УКРАЇНИ НАКАЗ від 06.04.2026 Київ № 186 Текст.",
            canonical="https://tax.gov.ua/x/formi-zvitnosti/80085.html",
        ),
        "https://tax.gov.ua/x/formi-zvitnosti/print-80085.html",
        reference_index={("MINFIN_ORDER", "186"): "dps:80085"},
    )

    assert page.external_id == "dps:80085"
    assert page.published_at.isoformat() == "2026-04-22T16:30:00+00:00"
    assert page.section == "Форми звітності"
    assert page.author == "Департамент методології"
    assert page.references[0].number == "186"
    assert page.references[0].date.isoformat() == "2026-04-06"


def test_order_293_amends_249_relation_candidate() -> None:
    page = parse_print_page(
        _print_html(
            page_id="80206",
            title=(
                "Наказ Міністерства фінансів України від 02.06.2026 № 293 "
                "«Про внесення змін до наказу Міністерства фінансів України "
                "від 11 травня 2026 року № 249»"
            ),
            author="Департамент методології",
            published="13 липня 2026 о 14:48",
            section="Накази",
            body="Внести зміни до наказу Міністерства фінансів України від 11 травня 2026 року № 249.",
            canonical="https://tax.gov.ua/zakonodavstvo/podatkove-zakonodavstvo/nakazi/80206.html",
        ),
        "https://tax.gov.ua/zakonodavstvo/podatkove-zakonodavstvo/nakazi/print-80206.html",
        reference_index={("MINFIN_ORDER", "249"): "dps:80205", ("MINFIN_ORDER", "293"): "dps:80206"},
    )

    assert [(item.to_external_id, item.relation_type) for item in page.relation_candidates] == [
        ("dps:80205", RelationType.AMENDS)
    ]


def test_dps_letter_related_to_249_and_293() -> None:
    page = parse_print_page(
        _print_html(
            page_id="80200",
            title="Лист ДПС від 08.07.2026 № 15504/7/99-00-21-02-01-07",
            author=None,
            published="09 липня 2026 о 10:50",
            section="Листи",
            body=(
                "Повідомляє про наказ Міністерства фінансів України від 11.05.2026 № 249 "
                "із змінами, внесеними наказом Міністерства фінансів України від 02.06.2026 № 293."
            ),
            canonical="https://tax.gov.ua/zakonodavstvo/podatkove-zakonodavstvo/listi-dps/80200.html",
        ),
        "https://tax.gov.ua/zakonodavstvo/podatkove-zakonodavstvo/listi-dps/print-80200.html",
        reference_index={("MINFIN_ORDER", "249"): "dps:80205", ("MINFIN_ORDER", "293"): "dps:80206"},
    )

    assert {
        (item.to_external_id, item.relation_type) for item in page.relation_candidates
    } == {
        ("dps:80205", RelationType.RELATED_TO),
        ("dps:80206", RelationType.RELATED_TO),
    }


def test_crs_316_reference_and_effective_date() -> None:
    page = parse_print_page(
        _print_html(
            page_id="1025759",
            title="CRS 2.0: в Україні запроваджують нові правила звітності",
            author="Пресслужба Державної податкової служби України",
            published="30 червня 2026 о 12:10",
            section="Новини",
            body=(
                "З 1 липня 2026 року почнуть діяти вимоги. "
                "Зміни затверджені наказом Міністерства фінансів України від 15.06.2026 № 316."
            ),
            canonical="https://tax.gov.ua/media-tsentr/novini/1025759.html",
        ),
        "https://tax.gov.ua/media-tsentr/novini/print-1025759.html",
    )

    assert page.effective_at.isoformat() == "2026-07-01T00:00:00+00:00"
    assert page.references[0].issuer == "MINFIN"
    assert page.references[0].number == "316"
    assert page.references[0].date.isoformat() == "2026-06-15"


def test_parse_document_references_tolerates_missing_optional_fields() -> None:
    assert parse_document_references("No strict document references here.") == []


def _print_html(
    page_id: str,
    title: str,
    author: str | None,
    published: str,
    section: str,
    body: str,
    canonical: str,
) -> str:
    author_text = f"{author}, " if author else ""
    return f"""
    <html><head><title>{title}</title></head>
    <body><div class="print">
      <h1>{title}</h1>
      <p>{author_text}опубліковано {published}</p>
      <p>Розділ: {section}</p>
      <div class="content"><p>{body}</p></div>
      <div class="print__footer"><p>© 2026 Державна податкова служба України</p><p>{canonical}</p></div>
    </div></body></html>
    """
