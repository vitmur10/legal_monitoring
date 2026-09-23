from app.sources.base import RawDocument
from app.sources.minfin.adapter import MinfinAdapter
from app.sources.minfin.parser import semantic_content


async def test_minfin_adapter_normalizes_semantic_content_and_metadata() -> None:
    adapter = MinfinAdapter()
    raw = RawDocument(
        source_code="minfin",
        external_id="page:578",
        canonical_url="https://mof.gov.ua/uk/crs-578",
        title=" CRS ",
        content=semantic_content(title="CRS", body="Важливий зміст"),
        document_type="CRS",
        metadata={"attachments": [], "references": []},
    )

    normalized = await adapter.normalize(raw)

    assert normalized.source_code == "minfin"
    assert normalized.external_id == "page:578"
    assert normalized.title == "CRS"
    assert "Важливий зміст" in normalized.content
