from datetime import date

from app.models.enums import RelationType
from app.sources.rada.parser import (
    extract_article_text,
    parse_card,
    parse_updated_documents,
)
from app.sources.rada.schemas import RadaRevisionState


def test_parse_updated_documents_from_r_json_payload() -> None:
    payload = {
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
                "pridat": "20101204",
                "num": "1",
            }
        ],
    }

    [stub] = parse_updated_documents(payload)

    assert stub.nreg == "2755-17"
    assert stub.title == "Podatkovyi kodeks Ukrainy"
    assert stub.dokid == 25613
    assert stub.type_ids == [21, 1]
    assert stub.issuer_id == 185
    assert stub.adoption_date == date(2010, 12, 2)
    assert stub.document_number == "2755-VI"
    assert stub.event_date == date(2026, 4, 15)
    assert stub.publication_date == date(2010, 12, 4)


def test_parse_card_revision_metadata_and_relation_candidates() -> None:
    current_card = {
        "nreg": "2755-17",
        "dokid": "25613",
        "nazva": "Podatkovyi kodeks Ukrainy",
        "status": "5",
        "types": "21|1",
        "organs": "185:20101202:2755-VI",
        "datred": "20260801",
        "pidstava": "4835-20",
        "hist": [{"podid": "1", "poddat": "20110101"}],
        "publics": [{"pubdat": "20101204"}],
        "edcnt": "3",
        "eds": [
            {"datred": "20260415", "pidstava": "ed20260415", "podid": "2"},
            {"datred": "20260801", "pidstava": "4835-20", "podid": "2"},
        ],
    }
    selected_card = {**current_card, "datred": "20260415", "pidstava": "ed20260415"}

    card = parse_card(selected_card, current_card_json=current_card)

    assert card.nreg == "2755-17"
    assert card.type_ids == [21, 1]
    assert card.current_revision_date == date(2026, 8, 1)
    assert card.effective_date == date(2011, 1, 1)
    assert card.publication_date == date(2010, 12, 4)
    assert [revision.state for revision in card.revisions] == [
        RadaRevisionState.PREVIOUS,
        RadaRevisionState.CURRENT,
    ]
    assert [
        (candidate.from_external_id, candidate.to_external_id, candidate.relation_type)
        for candidate in card.relation_candidates
    ] == [("ed20260415", "2755-17", RelationType.AMENDS)]
    assert {
        (
            candidate.from_external_id,
            candidate.to_external_id,
            candidate.relation_type,
            candidate.metadata["basis_for_revision_date"],
        )
        for candidate in card.historical_relation_candidates
    } == {
        ("ed20260415", "2755-17", RelationType.AMENDS, "2026-04-15"),
        ("4835-20", "2755-17", RelationType.AMENDS, "2026-08-01"),
    }


def test_extract_article_text_rejects_placeholder_and_reads_article() -> None:
    html = """
    <html><body>
      <div id="article">
        <h1>Title</h1>
        <p>First   paragraph.</p>
        <script>ignored()</script>
        <p>Second paragraph.</p>
      </div>
    </body></html>
    """

    assert extract_article_text(html) == "Title\nFirst paragraph.\nSecond paragraph."
