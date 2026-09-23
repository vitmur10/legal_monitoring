from datetime import date

from app.sources.minfin.parser import (
    external_id_from_url,
    order_external_id,
    parse_consultation_table,
    parse_document_references,
    parse_order_table,
    parse_page,
    parse_source_date,
)
from app.sources.minfin.schemas import MinfinDocumentType


CRS_HTML = """
<html><head><title>noise</title></head><body>
<header>Global nav <a href="/uk/search">search</a></header>
<main class="content">
  <h1>CRS: автоматичний обмін інформацією про фінансові рахунки</h1>
  <p>Порядок застосування CRS затверджений наказом Мінфіну від 26 травня 2023 року № 282.</p>
  <p>Зміни затверджені наказом Мінфіну від 15 червня 2026 року № 316 та наказом Мінфіну від 25 червня 2026 року № 338.</p>
  <p>Ці зміни набирають чинності з 1 липня 2026 року.</p>
  <p><a href="https://zakon.rada.gov.ua/laws/show/z0707-23#Text">Порядок CRS</a></p>
  <p><a href="/storage/files/Наказ_316.pdf">Наказ_316.pdf</a></p>
  <p><a href="/storage/files/Зміни_наказ_316.pdf">Зміни_наказ_316.pdf</a></p>
</main>
<footer>Newsletter Social UI</footer>
</body></html>
"""

ORDERS_HTML = """
<table>
  <tr>
    <td>26.06.2026</td>
    <td>Наказ Міністерства фінансів України від 15.06.2026 № 316 "Про затвердження Змін до Порядку застосування CRS"</td>
    <td><a href="/storage/files/Наказ_316.pdf">Наказ_316.pdf</a><a href="/storage/files/Зміни_наказ_316.pdf">Зміни_наказ_316.pdf</a></td>
  </tr>
  <tr>
    <td>08.06.2026</td>
    <td>Наказ Міністерства фінансів України від 11 травня 2026 року № 249 "Про затвердження Змін до форми Податкової декларації з податку на прибуток підприємств"</td>
    <td><a href="/storage/files/Наказ №249.pdf">Наказ №249.pdf</a><a href="/storage/files/Зміни_до наказу №249.pdf">Зміни_до наказу №249.pdf</a></td>
  </tr>
  <tr>
    <td>17.06.2026</td>
    <td>Наказ Міністерства фінансів України від 01 червня 2026 року № 292 "Про затвердження Змін до Національного положення (стандарту) бухгалтерського обліку в державному секторі 132 "Виплати працівникам""</td>
    <td><a href="/storage/files/Додаток-292.pdf">Додаток. Зміни</a></td>
  </tr>
  <tr><td>bad</td><td>Немає номера</td></tr>
</table>
"""

CONSULTATIONS_HTML = """
<table>
  <tr>
    <td>12.06.2026</td>
    <td>Наказ Міністерства фінансів України від 12.06.2026 № 314 "Про затвердження Узагальнюючої податкової консультації щодо пункту 197.23 статті 197 Податкового кодексу України"</td>
    <td><a href="/storage/files/Наказ_УПК_оборонні закупівлі.pdf">Наказ УПК</a><a href="/storage/files/УПК оборонні закупівлі.pdf">Консультація</a></td>
  </tr>
</table>
"""


def test_minfin_identity_strategies() -> None:
    assert external_id_from_url("https://mof.gov.ua/uk/crs-578") == "page:578"
    assert external_id_from_url("https://mof.gov.ua/uk/tax-policy") == "path:/uk/tax-policy"
    assert external_id_from_url("https://www.mof.gov.ua/uk/news/name-5797") == "news:5797"
    assert order_external_id(date(2026, 6, 15), "316") == "order:2026-06-15:316"


def test_minfin_ukrainian_date_parsing() -> None:
    assert parse_source_date("15.06.2026") == date(2026, 6, 15)
    assert parse_source_date("15 червня 2026 року") == date(2026, 6, 15)
    assert parse_source_date("bad") is None


def test_minfin_order_reference_regex_numeric_and_month_names() -> None:
    refs = parse_document_references(
        "Наказ Міністерства фінансів України від 15.06.2026 № 316; "
        "наказом Мінфіну від 15 червня 2026 року № 316"
    )
    assert refs[0].kind == "MINFIN_ORDER"
    assert refs[0].number == "316"
    assert refs[0].date == date(2026, 6, 15)


def test_minfin_static_page_extraction_attachments_rada_and_crs_references() -> None:
    page = parse_page(CRS_HTML, "https://mof.gov.ua/uk/crs-578")

    assert page.external_id == "page:578"
    assert page.title == "CRS: автоматичний обмін інформацією про фінансові рахунки"
    assert page.document_type == MinfinDocumentType.CRS
    assert "Global nav" not in page.body
    assert "Newsletter" not in page.body
    assert page.effective_at is not None
    assert page.effective_at.date() == date(2026, 7, 1)
    assert {attachment.label for attachment in page.attachments} == {"Наказ_316.pdf", "Зміни_наказ_316.pdf"}
    assert {reference.number for reference in page.references if reference.kind == "MINFIN_ORDER"} == {"282", "316", "338"}
    assert any(reference.kind == "RADA_DOCUMENT" for reference in page.references)


def test_minfin_order_table_row_parsing_316_249_292_and_malformed() -> None:
    rows = parse_order_table(
        ORDERS_HTML,
        "https://mof.gov.ua/uk/orders_of_the_Ministry_of_Finance_of_Ukraine_in_2026.",
    )

    by_id = {row.external_id: row for row in rows}
    assert set(by_id) == {"order:2026-06-15:316", "order:2026-05-11:249", "order:2026-06-01:292"}
    assert by_id["order:2026-06-15:316"].row_date == date(2026, 6, 26)
    assert by_id["order:2026-06-15:316"].order_number == "316"
    assert {item.label for item in by_id["order:2026-06-15:316"].attachments} == {"Наказ_316.pdf", "Зміни_наказ_316.pdf"}
    assert "Наказ №249.pdf" in {item.label for item in by_id["order:2026-05-11:249"].attachments}
    assert "Зміни_до наказу №249.pdf" in {item.label for item in by_id["order:2026-05-11:249"].attachments}
    assert by_id["order:2026-06-01:292"].document_type == MinfinDocumentType.ACCOUNTING
    assert "Виплати працівникам" in by_id["order:2026-06-01:292"].title
    assert by_id["order:2026-06-01:292"].attachments[0].label == "Додаток. Зміни"


def test_minfin_consultation_table_parsing_314_tax_code_references() -> None:
    rows = parse_consultation_table(
        CONSULTATIONS_HTML,
        "https://mof.gov.ua/uk/set-of-summarizing-tax-consultations",
    )

    assert len(rows) == 1
    row = rows[0]
    assert row.external_id == "general_tax_consultation:2026-06-12:314"
    assert row.order_number == "314"
    assert row.order_date == date(2026, 6, 12)
    assert len(row.attachments) == 2
    assert row.tax_code_references
