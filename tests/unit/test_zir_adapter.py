from app.sources.base import RawDocument
from app.sources.zir.adapter import ZirAdapter
from app.sources.zir.schemas import ZirStatus


class FakeZirClient:
    def __init__(self) -> None:
        self.initialized = 0
        self.search_calls = []
        self.load_more_calls = 0
        self.page_calls = []
        self.answer_calls = []

    async def initialize_session(self) -> str:
        self.initialized += 1
        return "<html>search</html>"

    async def search_consultations(self, **kwargs) -> str:
        self.search_calls.append(kwargs)
        return _search_xml(
            """
            <div id="result_row" row-id="38043">
              <div id="cat"><span>Категорія: 101.01 платники податку</span></div>
              <div id="title"><a href="/main/bz/view/?src=ques&amp;id=38043">
                <span>Які платники ЄП можуть бути платниками ПДВ?</span></a></div>
              <div class="actual">Чинна</div>
            </div>
            """,
            1,
        )

    async def load_more(self, srch_words: str = "") -> str:
        self.load_more_calls += 1
        return _load_more_xml(
            """
            <div id="result_row" quesid="33804">
              <div id="title"><a href="/main/bz/view/?src=ques&amp;id=33804">
                <span>Діяло до 23.05.2020 Як оподатковуються ПДВ операції?</span></a></div>
            </div>
            """
        )

    async def get_consultation_page(self, zir_id: str, src: str = "ques") -> str:
        self.page_calls.append((src, zir_id))
        if zir_id == "bad":
            raise ValueError("broken ZIR item")
        return f"""
        <div id="bz_hide_window_content">
          <fieldset><legend>Питання</legend>
            {'Діяло до 23.05.2020 Як оподатковуються ПДВ операції?' if zir_id == '33804' else 'Які платники ЄП можуть бути платниками ПДВ?'}
          </fieldset>
          <fieldset><legend>Відповідь</legend>
            Коротка:<br />Так.<br />Повна:<br />п. 180.1 ст. 180 ПКУ № 2755-VI.
            {'Коментар: Запитання-відповідь переведено до нечинних через Закон України № 466-IX.' if zir_id == '33804' else ''}
          </fieldset>
        </div>
        """

    async def get_answer_content(self, zir_id: str, src: str = "ques", srch_words: str = "") -> str:
        self.answer_calls.append((src, zir_id))
        return "Коротка:<br />Fallback.<br />Повна:<br />Fallback full."

    async def get_category_path(self, cat_id: str) -> str:
        return """
        <select><option value="1">101. Податок на додану вартість</option></select>
        <select><option value="4709">101.01 платники податку</option></select>
        """


async def test_zir_adapter_discovers_items_with_bounded_load_more() -> None:
    client = FakeZirClient()
    adapter = ZirAdapter(client=client, category_ids=["1"], max_load_more_batches=1, discovery_limit=None)

    items = await adapter.fetch_items()

    assert [item.external_id for item in items] == ["ques:38043", "ques:33804"]
    assert client.initialized == 1
    assert client.load_more_calls == 1


async def test_zir_adapter_fetches_and_normalizes_current_consultation() -> None:
    adapter = ZirAdapter(client=FakeZirClient(), max_load_more_batches=0)

    raw = await adapter.fetch_document(
        RawDocument(
            source_code="zir",
            external_id="ques:38043",
            canonical_url="https://zir.tax.gov.ua/main/bz/view/?src=ques&id=38043",
            title="Які платники ЄП можуть бути платниками ПДВ?",
            metadata={"src": "ques", "zir_id": "38043", "category": "101.01 платники податку", "status": "CURRENT"},
        )
    )
    normalized = await adapter.normalize(raw)

    assert normalized.external_id == "ques:38043"
    assert normalized.canonical_url == "https://zir.tax.gov.ua/main/bz/view/?src=ques&id=38043"
    assert normalized.title == "Які платники ЄП можуть бути платниками ПДВ?"
    assert normalized.metadata["status"] == ZirStatus.CURRENT
    assert normalized.metadata["category"] == "101.01 платники податку"
    assert normalized.metadata["normative_references"]
    assert "Question:" in normalized.content


async def test_zir_adapter_fetches_archived_consultation_33804() -> None:
    adapter = ZirAdapter(client=FakeZirClient(), max_load_more_batches=0)

    raw = await adapter.fetch_by_id("33804")
    normalized = await adapter.normalize(raw)

    assert normalized.external_id == "ques:33804"
    assert normalized.metadata["status"] == "NON_CURRENT"
    assert "Діяло до 23.05.2020" in normalized.title
    assert any(ref["number"] == "466-IX" for ref in normalized.metadata["normative_references"])


async def test_zir_adapter_category_discovery() -> None:
    adapter = ZirAdapter(client=FakeZirClient(), category_ids=["1"])

    categories = await adapter.fetch_categories()

    assert [category.id for category in categories] == ["1", "4709"]


async def test_zir_adapter_uses_ajax_answer_as_fallback_when_page_answer_missing() -> None:
    class FallbackClient(FakeZirClient):
        async def get_consultation_page(self, zir_id: str, src: str = "ques") -> str:
            return "<fieldset><legend>Питання</legend>Question</fieldset><fieldset><legend>Відповідь</legend> </fieldset>"

    client = FallbackClient()
    adapter = ZirAdapter(client=client)

    raw = await adapter.fetch_by_id("1")

    assert client.answer_calls == [("ques", "1")]
    assert "Fallback full" in raw.content


def test_zir_adapter_identity_from_canonical_url() -> None:
    adapter = ZirAdapter(client=FakeZirClient())

    assert adapter._identity_from_item(
        RawDocument(source_code="zir", canonical_url="https://zir.tax.gov.ua/main/bz/view/?src=ques&id=38043")
    ) == ("ques", "38043")


def _search_xml(content_html: str, count: int) -> str:
    escaped = (
        content_html.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
    return f'<?xml version="1.0" encoding="UTF-8"?><body><count>{count}</count><content>{escaped}</content></body>'


def _load_more_xml(content_html: str) -> str:
    escaped = (
        content_html.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
    return f'<?xml version="1.0" encoding="UTF-8"?><body><content>{escaped}</content></body>'
