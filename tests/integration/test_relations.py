from app.models.enums import RelationType
from app.models.document_relation import DocumentRelation
from app.repositories.relation_repository import DocumentRelationRepository
from app.services.versioning_service import VersioningService
from app.sources.mock import MockSourceAdapter
from tests.fixtures.builders import raw_document, source
from sqlalchemy import select


async def _create_doc(session, db_source, external_id: str, title: str):
    raw = raw_document(external_id=external_id, title=title, content=title)
    normalized = await MockSourceAdapter().normalize(raw)
    result = await VersioningService().process_document(session, db_source, normalized, raw.content or "")
    await session.commit()
    return result.document_id


async def test_document_relation_can_be_created(session):
    db_source = source()
    session.add(db_source)
    await session.commit()
    await session.refresh(db_source)
    order_249_id = await _create_doc(session, db_source, "order-249", "Minfin Order #249")
    order_293_id = await _create_doc(session, db_source, "order-293", "Minfin Order #293")

    relation = await DocumentRelationRepository(session).create(
        from_document_id=order_293_id,
        to_document_id=order_249_id,
        relation_type=RelationType.AMENDS,
    )
    await session.commit()

    assert relation.id is not None


async def test_document_relation_chain_can_be_fetched(session):
    db_source = source()
    session.add(db_source)
    await session.commit()
    await session.refresh(db_source)
    order_249_id = await _create_doc(session, db_source, "order-249", "Minfin Order #249")
    order_293_id = await _create_doc(session, db_source, "order-293", "Minfin Order #293")
    letter_id = await _create_doc(session, db_source, "letter-15504", "Tax authority explanation")

    repo = DocumentRelationRepository(session)
    await repo.create(order_293_id, order_249_id, RelationType.AMENDS)
    await repo.create(letter_id, order_293_id, RelationType.EXPLAINS)
    await session.commit()

    chain = await repo.fetch_chain(order_249_id)

    assert len(chain) == 2
    assert {relation.relation_type for relation in chain} == {RelationType.AMENDS, RelationType.EXPLAINS}


async def test_explicit_relation_candidates_are_resolved_without_duplicates(session):
    db_source = source(code="rada")
    session.add(db_source)
    await session.commit()
    await session.refresh(db_source)

    service = VersioningService()
    tax_code = raw_document(
        external_id="2755-17",
        title="Tax Code",
        content="Tax Code content",
        source_code="rada",
    )
    normalized_tax_code = await MockSourceAdapter(source_code="rada").normalize(tax_code)
    normalized_tax_code.metadata["historical_relation_candidates"] = [
        {
            "from_external_id": "4835-20",
            "to_external_id": "2755-17",
            "relation_type": "AMENDS",
            "source": "rada",
            "metadata": {
                "basis_for_revision_date": "2026-04-15",
                "basis_scope": "revision_history",
                "deterministic": True,
                "explicit": True,
            },
        }
    ]

    first = await service.process_document(session, db_source, normalized_tax_code, tax_code.content or "")
    assert first.document_id is not None
    assert (await session.execute(select(DocumentRelation))).scalars().all() == []

    amending_law = raw_document(
        external_id="4835-20",
        title="Law 4835",
        content="Law 4835 content",
        source_code="rada",
    )
    normalized_amending_law = await MockSourceAdapter(source_code="rada").normalize(amending_law)
    second = await service.process_document(
        session, db_source, normalized_amending_law, amending_law.content or ""
    )
    await session.commit()

    assert second.document_id is not None
    relations = (await session.execute(select(DocumentRelation))).scalars().all()
    assert len(relations) == 1
    assert relations[0].from_document_id == second.document_id
    assert relations[0].to_document_id == first.document_id
    assert relations[0].relation_type == RelationType.AMENDS
    assert relations[0].relation_metadata["basis_for_revision_date"] == "2026-04-15"
    assert relations[0].relation_metadata["source"] == "rada"

    await service.process_document(session, db_source, normalized_tax_code, tax_code.content or "")
    await service.process_document(session, db_source, normalized_amending_law, amending_law.content or "")
    await session.commit()

    relations = (await session.execute(select(DocumentRelation))).scalars().all()
    assert len(relations) == 1
