import pytest

from app.sources.zir.parser import (
    canonical_url,
    external_id,
    extract_normative_references,
    parse_answer_fragment,
    parse_category_path,
    parse_consultation_page,
    parse_external_id,
    parse_load_more_response,
    parse_search_response,
    semantic_content,
    validate_ajax_xml,
)
from app.sources.zir.schemas import ZirStatus


CURRENT_HTML = """
<div id="bz_hide_window_content">
  <fieldset class="bz_hide_fieldset ques"><legend>Питання</legend>
    <span>Які платники ЄП можуть бути платниками ПДВ?</span>
  </fieldset>
  <fieldset class="bz_hide_fieldset answ"><legend>Відповідь</legend>
    <span><strong>Коротка:</strong><br />Платники єдиного податку третьої групи.<br />
    <strong>Повна:</strong><br />Відповідно до п. 180.1 ст. 180 Податкового кодексу України
    від 02 грудня 2010 року № 2755-VI платником податку є особа.</span>
  </fieldset>
</div>
"""


ARCHIVED_HTML = """
<div id="bz_hide_window_content">
  <fieldset><legend>Питання</legend>
    <span>Діяло до 23.05.2020 Як оподатковуються ПДВ операції?</span>
  </fieldset>
  <fieldset><legend>Відповідь</legend>
    <span>Діяла до 23.05.2020 Коротка та повна відповіді ідентичні.<br />
    Коментар: «Запитання-відповідь переведено до нечинних у зв’язку з набранням чинності
    Законом України від 16 січня 2020 року № 466-IX».</span>
  </fieldset>
</div>
"""


def test_external_id_parsing() -> None:
    assert external_id("ques", "38043") == "ques:38043"
    assert parse_external_id("ques:33804") == ("ques", "33804")
    assert canonical_url("ques", "38043").endswith("/main/bz/view/?src=ques&id=38043")


def test_search_xml_like_response_and_escaped_html_parsing() -> None:
    response = _search_xml(
        """
        <div id="result_row" ques row-id="38043">
          <div id="cat" title="Категорія: 101.01 платники податку">
            <span>Категорія: 101.01 платники податку</span>
          </div>
          <div id="title"><a href="/main/bz/view/?src=ques&amp;id=38043">
            <span>Які платники ЄП можуть бути платниками ПДВ?</span></a></div>
          <div class="actual">Чинна</div>
        </div>
        """,
        count=1,
    )

    result = parse_search_response(response, default_status=ZirStatus.CURRENT)

    assert result.count == 1
    assert result.items[0].external_id == "ques:38043"
    assert result.items[0].question == "Які платники ЄП можуть бути платниками ПДВ?"
    assert result.items[0].category == "101.01 платники податку"
    assert result.items[0].status == ZirStatus.CURRENT


def test_load_more_legacy_quesid_parsing() -> None:
    response = """<?xml version="1.0" encoding="UTF-8"?><body><content>
    &lt;div id=&quot;result_row&quot; quesid=&quot;35130&quot;&gt;
      &lt;div id=&quot;title&quot;&gt;&lt;a href=&quot;/main/bz/view/?src=ques&amp;amp;id=35130&quot;&gt;
      &lt;span&gt;Чи подається заява?&lt;/span&gt;&lt;/a&gt;&lt;/div&gt;
    &lt;/div&gt;</content></body>"""

    result = parse_load_more_response(response, default_status=ZirStatus.CURRENT)

    assert [item.external_id for item in result.items] == ["ques:35130"]


def test_category_path_parsing() -> None:
    html = """
    <select id="srch_cat">
      <option value="0">Оберіть категорію</option>
      <option value="1" selected>101. Податок на додану вартість</option>
      <option value="-1" disabled>-----</option>
    </select>
    <select id="srch_cat">
      <option value="4709">101.01 платники податку</option>
    </select>
    """

    categories = parse_category_path(html)

    assert categories[0].id == "1"
    assert categories[0].code == "101"
    assert categories[0].title == "Податок на додану вартість"
    assert categories[1].id == "4709"
    assert categories[1].code == "101.01"


def test_answer_fragment_splits_short_and_full_answers() -> None:
    answer = parse_answer_fragment(
        "Коротка:<br />Так.<br />Повна:<br />Відповідно до п. 181.1 ст. 181 ПКУ текст.<br />[1|0|0|0|1]"
    )

    assert answer.short_answer == "Так."
    assert answer.full_answer == "Відповідно до п. 181.1 ст. 181 ПКУ текст."


def test_canonical_current_consultation_fixture_38043() -> None:
    page = parse_consultation_page(
        CURRENT_HTML,
        "https://zir.tax.gov.ua/main/bz/view/?src=ques&id=38043",
    )

    assert page.external_id == "ques:38043"
    assert page.question == "Які платники ЄП можуть бути платниками ПДВ?"
    assert page.status == ZirStatus.UNKNOWN
    assert page.short_answer
    assert page.full_answer
    assert any(ref.paragraph == "180.1" and ref.article == "180" for ref in page.normative_references)


def test_canonical_archived_consultation_fixture_33804() -> None:
    page = parse_consultation_page(
        ARCHIVED_HTML,
        "https://zir.tax.gov.ua/main/bz/view/?src=ques&id=33804",
    )

    assert page.external_id == "ques:33804"
    assert page.status == ZirStatus.NON_CURRENT
    assert "Діяло до 23.05.2020" in page.question
    assert page.comments
    assert any(ref.number == "466-IX" for ref in page.normative_references)


def test_normative_reference_patterns() -> None:
    refs = extract_normative_references(
        "п. 180.1 ст. 180, п. 181.1 ст. 181, п. 293.3 ст. 293 ПКУ № 2755-VI "
        "та Закон України № 466-IX."
    )

    assert {ref.paragraph for ref in refs if ref.paragraph} == {"180.1", "181.1", "293.3"}
    assert any(ref.number == "2755-VI" for ref in refs)
    assert any(ref.number == "466-IX" for ref in refs)


def test_malformed_http_200_html_error_detection() -> None:
    with pytest.raises(ValueError):
        validate_ajax_xml(
            "<!DOCTYPE html><html><head><title>Помилка</title></head><body>bad</body></html>",
            ("count", "content"),
        )


def test_missing_optional_fields_are_tolerated() -> None:
    page = parse_consultation_page(
        """
        <fieldset><legend>Питання</legend>Питання без категорії</fieldset>
        <fieldset><legend>Відповідь</legend>Проста відповідь.</fieldset>
        """,
        "https://zir.tax.gov.ua/main/bz/view/?src=ques&id=1",
    )

    assert page.category is None
    assert page.short_answer is None
    assert page.full_answer == "Проста відповідь."


def test_semantic_content_excludes_raw_html_noise() -> None:
    page = parse_consultation_page(
        CURRENT_HTML,
        "https://zir.tax.gov.ua/main/bz/view/?src=ques&id=38043",
    )

    content = semantic_content(page)

    assert "<fieldset" not in content
    assert "PHPSESSID" not in content
    assert "Question: Які платники" in content


def _search_xml(content_html: str, count: int) -> str:
    escaped = (
        content_html.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
    return f'<?xml version="1.0" encoding="UTF-8"?><body><count>{count}</count><content>{escaped}</content></body>'
