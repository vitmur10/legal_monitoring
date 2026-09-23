import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.repositories.source_repository import SourceRepository
from app.services.monitoring_service import MonitoringService
from app.sources.registry import SourceRegistry

logger = logging.getLogger(__name__)


class MonitoringScheduler:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        registry: SourceRegistry,
    ) -> None:
        self.session_factory = session_factory
        self.registry = registry
        self.scheduler = AsyncIOScheduler()

    async def start(self) -> None:
        async with self.session_factory() as session:
            sources = await SourceRepository(session).list(enabled=True)

        service = MonitoringService(self.session_factory, self.registry)
        for source in sources:
            try:
                self.registry.get(source.code)
            except KeyError:
                logger.warning("scheduler_skipped_unregistered_source source=%s", source.code)
                continue
            self.scheduler.add_job(
                service.run_source,
                "interval",
                minutes=source.check_interval_minutes,
                args=[source.id],
                id=f"source:{source.id}",
                replace_existing=True,
                max_instances=1,
            )
        self.scheduler.start()

    def shutdown(self) -> None:
        self.scheduler.shutdown(wait=False)
