from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.repositories.monitoring_run_repository import MonitoringRunRepository
from app.schemas.common import MonitoringRunRead

router = APIRouter(prefix="/monitoring", tags=["monitoring"])


@router.get("/runs", response_model=list[MonitoringRunRead])
async def list_runs(session: AsyncSession = Depends(get_session)) -> list:
    return await MonitoringRunRepository(session).list()
