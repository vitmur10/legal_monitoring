from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.repositories.document_repository import DocumentRepository
from app.repositories.relation_repository import DocumentRelationRepository
from app.schemas.common import (
    DocumentRead,
    DocumentRelationCreate,
    DocumentRelationRead,
    DocumentVersionRead,
)

router = APIRouter(prefix="/documents", tags=["documents"])


@router.get("", response_model=list[DocumentRead])
async def list_documents(session: AsyncSession = Depends(get_session)) -> list:
    return await DocumentRepository(session).list()


@router.get("/{document_id}", response_model=DocumentRead)
async def get_document(document_id: int, session: AsyncSession = Depends(get_session)):
    document = await DocumentRepository(session).get(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return document


@router.get("/{document_id}/versions", response_model=list[DocumentVersionRead])
async def get_versions(document_id: int, session: AsyncSession = Depends(get_session)) -> list:
    return await DocumentRepository(session).versions(document_id)


@router.get("/{document_id}/versions/{version_id}/stage2")
async def get_stage2_result(
    document_id: int,
    version_id: int,
    session: AsyncSession = Depends(get_session),
) -> dict:
    version = await DocumentRepository(session).get_version(version_id)
    if version is None or version.document_id != document_id:
        raise HTTPException(status_code=404, detail="Document version not found")
    stage2 = (version.version_metadata or {}).get("stage2")
    if stage2 is None:
        raise HTTPException(status_code=404, detail="Stage 2 result not found")
    return stage2


@router.get("/{document_id}/relations", response_model=list[DocumentRelationRead])
async def get_relations(document_id: int, session: AsyncSession = Depends(get_session)) -> list:
    return await DocumentRelationRepository(session).fetch_chain(document_id)


@router.post("/{document_id}/relations", response_model=DocumentRelationRead)
async def create_relation(
    document_id: int,
    payload: DocumentRelationCreate,
    session: AsyncSession = Depends(get_session),
):
    if await DocumentRepository(session).get(document_id) is None:
        raise HTTPException(status_code=404, detail="Document not found")
    if await DocumentRepository(session).get(payload.to_document_id) is None:
        raise HTTPException(status_code=404, detail="Target document not found")
    relation = await DocumentRelationRepository(session).create(
        from_document_id=document_id,
        to_document_id=payload.to_document_id,
        relation_type=payload.relation_type,
        metadata=payload.metadata,
    )
    await session.commit()
    await session.refresh(relation)
    return relation
