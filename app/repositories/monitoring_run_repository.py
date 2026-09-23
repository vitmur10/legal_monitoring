from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import MonitoringRunStatus
from app.models.monitoring_run import MonitoringRun


class MonitoringRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, source_id: int) -> MonitoringRun:
        run = MonitoringRun(
            source_id=source_id,
            started_at=datetime.now(timezone.utc),
            status=MonitoringRunStatus.RUNNING,
        )
        self.session.add(run)
        await self.session.flush()
        return run

    async def get(self, run_id: int) -> MonitoringRun | None:
        return await self.session.get(MonitoringRun, run_id)

    async def list(self, limit: int = 100) -> list[MonitoringRun]:
        result = await self.session.execute(
            select(MonitoringRun).order_by(MonitoringRun.started_at.desc()).limit(limit)
        )
        return list(result.scalars().all())

    async def finish(
        self,
        run: MonitoringRun,
        status: MonitoringRunStatus,
        error_message: str | None = None,
    ) -> None:
        run.finished_at = datetime.now(timezone.utc)
        run.status = status
        run.error_message = error_message
