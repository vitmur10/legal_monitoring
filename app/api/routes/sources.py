from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal, get_session
from app.repositories.source_repository import SourceRepository
from app.schemas.common import ProcessingResult, SourceRead
from app.services.monitoring_service import MonitoringService
from app.sources.registry import registry

router = APIRouter(prefix="/sources", tags=["sources"])


@router.get("", response_model=list[SourceRead])
async def list_sources(session: AsyncSession = Depends(get_session)) -> list:
    return await SourceRepository(session).list()


@router.get("/{source_id}", response_model=SourceRead)
async def get_source(source_id: int, session: AsyncSession = Depends(get_session)):
    source = await SourceRepository(session).get(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    return source


@router.post("/{source_id}/run", response_model=list[ProcessingResult])
async def run_source(source_id: int):
    service = MonitoringService(AsyncSessionLocal, registry)
    try:
        return await service.run_source(source_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
