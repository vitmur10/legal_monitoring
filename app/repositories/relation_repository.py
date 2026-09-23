from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document_relation import DocumentRelation
from app.models.enums import RelationType


class DocumentRelationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        from_document_id: int,
        to_document_id: int,
        relation_type: RelationType,
        metadata: dict | None = None,
    ) -> DocumentRelation:
        relation = DocumentRelation(
            from_document_id=from_document_id,
            to_document_id=to_document_id,
            relation_type=relation_type,
            relation_metadata=metadata or {},
        )
        self.session.add(relation)
        await self.session.flush()
        return relation

    async def exists(
        self,
        from_document_id: int,
        to_document_id: int,
        relation_type: RelationType,
    ) -> bool:
        result = await self.session.execute(
            select(DocumentRelation.id)
            .where(DocumentRelation.from_document_id == from_document_id)
            .where(DocumentRelation.to_document_id == to_document_id)
            .where(DocumentRelation.relation_type == relation_type)
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def list_for_document(self, document_id: int) -> list[DocumentRelation]:
        result = await self.session.execute(
            select(DocumentRelation)
            .where(
                or_(
                    DocumentRelation.from_document_id == document_id,
                    DocumentRelation.to_document_id == document_id,
                )
            )
            .order_by(DocumentRelation.id)
        )
        return list(result.scalars().all())

    async def fetch_chain(self, document_id: int, max_depth: int = 5) -> list[DocumentRelation]:
        seen_docs = {document_id}
        frontier = {document_id}
        relations: list[DocumentRelation] = []
        seen_relations: set[int] = set()

        for _ in range(max_depth):
            if not frontier:
                break
            result = await self.session.execute(
                select(DocumentRelation).where(
                    or_(
                        DocumentRelation.from_document_id.in_(frontier),
                        DocumentRelation.to_document_id.in_(frontier),
                    )
                )
            )
            next_frontier: set[int] = set()
            for relation in result.scalars().all():
                if relation.id not in seen_relations:
                    relations.append(relation)
                    seen_relations.add(relation.id)
                for doc_id in (relation.from_document_id, relation.to_document_id):
                    if doc_id not in seen_docs:
                        seen_docs.add(doc_id)
                        next_frontier.add(doc_id)
            frontier = next_frontier
        return relations
