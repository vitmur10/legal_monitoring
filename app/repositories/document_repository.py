from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.document import Document
from app.models.document_version import DocumentVersion


class DocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, document_id: int) -> Document | None:
        return await self.session.get(Document, document_id)

    async def list(self) -> list[Document]:
        result = await self.session.execute(select(Document).order_by(Document.id))
        return list(result.scalars().all())

    async def list_by_source_with_current_versions(self, source_id: int) -> list[Document]:
        result = await self.session.execute(
            select(Document)
            .where(Document.source_id == source_id)
            .options(selectinload(Document.current_version))
            .order_by(Document.id)
        )
        return list(result.scalars().all())

    async def get_by_identity_for_update(self, source_id: int, identity_key: str) -> Document | None:
        query = (
            select(Document)
            .where(Document.source_id == source_id, Document.identity_key == identity_key)
            .options(selectinload(Document.current_version))
            .with_for_update()
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def versions(self, document_id: int) -> list[DocumentVersion]:
        result = await self.session.execute(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document_id)
            .order_by(DocumentVersion.version_number)
        )
        return list(result.scalars().all())

    async def get_version(self, version_id: int) -> DocumentVersion | None:
        return await self.session.get(DocumentVersion, version_id)

    async def get_version_for_update(self, version_id: int) -> DocumentVersion | None:
        await self.session.flush()
        result = await self.session.execute(
            select(DocumentVersion)
            .where(DocumentVersion.id == version_id)
            .options(selectinload(DocumentVersion.document))
            .execution_options(populate_existing=True)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def list_versions_with_documents(self) -> list[DocumentVersion]:
        result = await self.session.execute(
            select(DocumentVersion)
            .options(selectinload(DocumentVersion.document))
            .order_by(DocumentVersion.detected_at.desc(), DocumentVersion.id.desc())
        )
        return list(result.scalars().all())

    async def latest_version_number(self, document_id: int) -> int:
        result = await self.session.execute(
            select(DocumentVersion.version_number)
            .where(DocumentVersion.document_id == document_id)
            .order_by(DocumentVersion.version_number.desc())
            .limit(1)
        )
        return result.scalar_one_or_none() or 0
