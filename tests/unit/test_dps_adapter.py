from app.sources.base import RawDocument
from app.sources.dps.adapter import DpsAdapter


class FakeDpsClient:
    def __init__(self) -> None:
        self.get_calls: list[str] = []
        self.post_calls: list[tuple[str, int]] = []

    async def get_text(self, url: str) -> str:
        self.get_calls.append(url)
        if url.endswith("/novini/"):
            return """
            <div class="news__item">
              <div class="shortnews__date">30 червня 2026</div>
              <a href="/media-tsentr/novini/1025759.html" class="news__title">CRS 2.0</a>
            </div>
            """
        if "print-1025759.html" in url:
            return _print_html()
        if "1025759.html" in url:
            return """
            <div class="materials-additional">
              <a href="/data/files/687542.pdf">Наказом (.pdf, 500 Kb)</a>
            </div>
            """
        if "print-80206.html" in url:
            return _order_293_print_html()
        if "80206.html" in url:
            return '<html><body><div class="materials-additional"></div></body></html>'
        raise AssertionError(f"Unexpected URL: {url}")

    async def post_more(self, section_url: str, page: int, date_from=None, date_to=None):
        self.post_calls.append((section_url, page))
        return {
            "feed": """
            <div class="news__item">
              <div class="shortnews__date">29 червня 2026</div>
              <a href="/media-tsentr/novini/1025000.html" class="news__title">Other</a>
            </div>
            """
        }


async def test_dps_adapter_discovers_initial_and_post_feed_items() -> None:
    client = FakeDpsClient()
    adapter = DpsAdapter(
        client=client,
        sections=["https://tax.gov.ua/media-tsentr/novini/"],
        max_pages_per_section=2,
    )

    items = await adapter.fetch_items()

    assert [item.external_id for item in items] == ["dps:1025759", "dps:1025000"]
    assert client.post_calls == [("https://tax.gov.ua/media-tsentr/novini/", 2)]


async def test_dps_adapter_fetches_print_content_and_normal_attachments() -> None:
    adapter = DpsAdapter(client=FakeDpsClient())

    raw = await adapter.fetch_by_page_id("1025759")
    normalized = await adapter.normalize(raw)

    assert raw.external_id == "dps:1025759"
    assert raw.canonical_url == "https://tax.gov.ua/media-tsentr/novini/1025759.html"
    assert raw.content and "З 1 липня 2026 року" in raw.content
    assert normalized.document_type == "NEWS"
    assert normalized.published_at.isoformat() == "2026-06-30T12:10:00+00:00"
    assert normalized.effective_at.isoformat() == "2026-07-01T00:00:00+00:00"
    assert normalized.metadata["attachments"][0]["url"] == "https://tax.gov.ua/data/files/687542.pdf"
    assert normalized.metadata["references"][0]["number"] == "316"


async def test_known_reference_index_overrides_ambiguous_discovery_mapping() -> None:
    adapter = DpsAdapter(client=FakeDpsClient())
    adapter._discovered_reference_index = {("MINFIN_ORDER", "249"): "dps:66630"}

    raw = await adapter.fetch_document(
        RawDocument(
            source_code="dps",
            external_id="dps:80206",
            canonical_url="https://www.tax.gov.ua/zakonodavstvo/podatkove-zakonodavstvo/nakazi/80206.html",
            metadata={"page_id": "80206"},
        )
    )

    assert raw.metadata["relation_candidates"][0]["to_external_id"] == "dps:80205"


def _order_293_print_html() -> str:
    return """
    <html><head><title>Наказ Міністерства фінансів України від 02.06.2026 № 293
    «Про внесення змін до наказу Міністерства фінансів України від 11 травня 2026 року № 249»</title></head>
    <body><div class="print">
      <h1>Наказ Міністерства фінансів України від 02.06.2026 № 293 «Про внесення змін до наказу Міністерства фінансів України від 11 травня 2026 року № 249»</h1>
      <p>Департамент методології, опубліковано 13 липня 2026 о 14:48</p>
      <p>Розділ: Накази</p>
      <p>Внести зміни до наказу Міністерства фінансів України від 11 травня 2026 року № 249.</p>
      <div class="print__footer"><p>https://www.tax.gov.ua/zakonodavstvo/podatkove-zakonodavstvo/nakazi/80206.html</p></div>
    </div></body></html>
    """


def _print_html() -> str:
    return """
    <html><head><title>CRS 2.0: в Україні запроваджують нові правила звітності</title></head>
    <body><div class="print">
      <h1>CRS 2.0: в Україні запроваджують нові правила звітності</h1>
      <p>Пресслужба Державної податкової служби України, опубліковано 30 червня 2026 о 12:10</p>
      <p>Розділ: Новини</p>
      <p>З 1 липня 2026 року почнуть діяти вимоги.</p>
      <p>Зміни затверджені наказом Міністерства фінансів України від 15.06.2026 № 316.</p>
      <div class="print__footer">
        <p>© 2026 Державна податкова служба України</p>
        <p>https://tax.gov.ua/media-tsentr/novini/1025759.html</p>
      </div>
    </div></body></html>
    """
