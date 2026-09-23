import pytest

from app.sources.base import RawDocument
from app.sources.rada.adapter import RadaAdapter
from app.sources.rada.client import RadaHTTPError


class FakeRadaClient:
    def __init__(self) -> None:
        self.card_calls: list[tuple[str, str | None]] = []
        self.document_html_calls: list[tuple[str, str | None]] = []
        self.print_html_calls: list[tuple[str, str | None]] = []
        self.fail_document_html = False

    async def get_updated_documents(self):
        return {
            "block": "main",
            "list": [
                {
                    "nreg": "2755-17",
                    "nazva": "Podatkovyi kodeks Ukrainy",
                    "dokid": "25613",
                    "status": "5",
                    "types": "21|1",
                    "organs": "185:20101202:2755-VI",
                    "poddat": "20260415",
                },
                {
                    "nreg": "4835-20",
                    "nazva": "Zakon Ukrainy",
                    "dokid": "4835",
                    "status": "5",
                    "types": "1",
                    "organs": "185:20220503:4835-IX",
                    "poddat": "20220503",
                },
            ],
        }

    async def get_card(self, nreg: str, revision_date: str | None = None):
        self.card_calls.append((nreg, revision_date))
        card = {
            "nreg": nreg,
            "dokid": "25613",
            "nazva": "Podatkovyi kodeks Ukrainy",
            "status": "5",
            "types": "21|1",
            "organs": "185:20101202:2755-VI",
            "datred": "20260801",
            "pidstava": "4835-20",
            "hist": [{"podid": "1", "poddat": "20110101"}],
            "publics": [{"pubdat": "20101204"}],
            "eds": [
                {"datred": "20260415", "pidstava": "ed20260415", "podid": "2"},
                {"datred": "20260801", "pidstava": "4835-20", "podid": "2"},
            ],
        }
        if revision_date:
            return {**card, "datred": revision_date, "pidstava": "ed20260415"}
        return card

    async def get_document_html(self, nreg: str, revision_date: str | None = None):
        self.document_html_calls.append((nreg, revision_date))
        if self.fail_document_html:
            raise RadaHTTPError(404, "https://data.rada.gov.ua/laws/show")
        return _article_html("Primary legal text")

    async def get_print_html(self, nreg: str, revision_date: str | None = None):
        self.print_html_calls.append((nreg, revision_date))
        return _article_html("Print legal text")


async def test_fetch_items_discovers_documents_from_r_json() -> None:
    adapter = RadaAdapter(client=FakeRadaClient(), discovery_limit=1)

    items = await adapter.fetch_items()

    assert len(items) == 1
    assert items[0].source_code == "rada"
    assert items[0].external_id == "2755-17"
    assert items[0].metadata["document_number"] == "2755-VI"
    assert items[0].metadata["event_date"] == "2026-04-15"


async def test_fetch_by_nreg_fetches_specific_revision_and_metadata() -> None:
    client = FakeRadaClient()
    adapter = RadaAdapter(client=client)

    document = await adapter.fetch_by_nreg("2755-17", "2026-04-15")

    assert client.card_calls == [("2755-17", None), ("2755-17", "20260415")]
    assert client.document_html_calls == [("2755-17", "20260415")]
    assert client.print_html_calls == []
    assert document.external_id == "2755-17"
    assert document.canonical_url == "https://zakon.rada.gov.ua/laws/show/2755-17/ed20260415"
    assert document.content == "Primary legal text"
    assert document.effective_at.isoformat() == "2011-01-01T00:00:00+00:00"
    assert document.metadata["revision_date"] == "2026-04-15"
    assert document.metadata["requested_revision_date"] == "20260415"
    assert document.metadata["specific_revision_basis_nregs"] == ["ed20260415"]
    assert [candidate["from_external_id"] for candidate in document.metadata["relation_candidates"]] == [
        "ed20260415"
    ]
    assert {candidate["from_external_id"] for candidate in document.metadata["historical_relation_candidates"]} == {
        "4835-20",
        "ed20260415",
    }


async def test_fetch_document_falls_back_to_print_html() -> None:
    client = FakeRadaClient()
    client.fail_document_html = True
    adapter = RadaAdapter(client=client)

    document = await adapter.fetch_document(RawDocument(source_code="rada", external_id="4835-20"))

    assert client.document_html_calls == [("4835-20", None)]
    assert client.print_html_calls == [("4835-20", None)]
    assert document.content == "Print legal text"


async def test_normalize_requires_content_external_id_and_title() -> None:
    adapter = RadaAdapter(client=FakeRadaClient())

    with pytest.raises(ValueError, match="content"):
        await adapter.normalize(RawDocument(source_code="rada", external_id="2755-17", title="Title"))


def _article_html(text: str) -> str:
    return f'<html><body><div id="article"><p>{text}</p></div></body></html>'
