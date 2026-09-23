import logging
import time
from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.enums import MonitoringRunStatus, ProcessingStatus
from app.repositories.monitoring_run_repository import MonitoringRunRepository
from app.repositories.source_repository import SourceRepository
from app.schemas.common import ProcessingResult
from app.services.versioning_service import VersioningService
from app.sources.registry import SourceRegistry

logger = logging.getLogger(__name__)


class MonitoringService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | Callable[[], AsyncSession],
        registry: SourceRegistry,
        versioning_service: VersioningService | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.registry = registry
        self.versioning_service = versioning_service or VersioningService()

    async def run_source(self, source_id: int) -> list[ProcessingResult]:
        async with self.session_factory() as session:
            source_repo = SourceRepository(session)
            run_repo = MonitoringRunRepository(session)
            source = await source_repo.get(source_id)
            if source is None:
                raise ValueError(f"Source {source_id} not found")
            adapter = self.registry.get(source.code)
            run = await run_repo.create(source.id)
            await session.commit()
            run_id = run.id

        started = time.perf_counter()
        results: list[ProcessingResult] = []
        error_message: str | None = None

        try:
            items = await adapter.fetch_items()
        except Exception as exc:
            error_message = str(exc)
            await self._finish_run(run_id, MonitoringRunStatus.FAILED, 0, results, error_message)
            logger.exception("monitoring_fetch_failed source=%s run_id=%s error=%s", adapter.source_code, run_id, exc)
            return [
                ProcessingResult(
                    status=ProcessingStatus.FAILED,
                    source_code=adapter.source_code,
                    error=error_message,
                )
            ]

        for item in items:
            item_started = time.perf_counter()
            try:
                raw = await adapter.fetch_document(item)
                normalized = await adapter.normalize(raw)
                async with self.session_factory() as session:
                    source = await SourceRepository(session).get(source_id)
                    if source is None:
                        raise ValueError(f"Source {source_id} not found")
                    result = await self.versioning_service.process_document(
                        session=session,
                        source=source,
                        normalized=normalized,
                        raw_content=raw.content or "",
                    )
                    await session.commit()
                results.append(result)
                logger.info(
                    "document_processed source=%s run_id=%s external_id=%s document_id=%s status=%s duration=%.3f",
                    adapter.source_code,
                    run_id,
                    result.external_id,
                    result.document_id,
                    result.status,
                    time.perf_counter() - item_started,
                )
            except Exception as exc:
                failed = ProcessingResult(
                    status=ProcessingStatus.FAILED,
                    source_code=adapter.source_code,
                    external_id=item.external_id,
                    error=str(exc),
                )
                results.append(failed)
                logger.exception(
                    "document_failed source=%s run_id=%s external_id=%s status=FAILED duration=%.3f error=%s",
                    adapter.source_code,
                    run_id,
                    item.external_id,
                    time.perf_counter() - item_started,
                    exc,
                )

        await self._finish_run(run_id, MonitoringRunStatus.COMPLETED, len(items), results, error_message)
        logger.info(
            "monitoring_run_completed source=%s run_id=%s duration=%.3f",
            adapter.source_code,
            run_id,
            time.perf_counter() - started,
        )
        return results

    async def _finish_run(
        self,
        run_id: int,
        status: MonitoringRunStatus,
        items_found: int,
        results: list[ProcessingResult],
        error_message: str | None,
    ) -> None:
        async with self.session_factory() as session:
            run_repo = MonitoringRunRepository(session)
            run = await run_repo.get(run_id)
            if run is None:
                raise ValueError(f"Monitoring run {run_id} not found")
            run.items_found = items_found
            run.new_count = sum(1 for result in results if result.status == ProcessingStatus.NEW)
            run.changed_count = sum(1 for result in results if result.status == ProcessingStatus.CHANGED)
            run.unchanged_count = sum(1 for result in results if result.status == ProcessingStatus.UNCHANGED)
            run.failed_count = sum(1 for result in results if result.status == ProcessingStatus.FAILED)
            await run_repo.finish(run, status, error_message)

            source = await SourceRepository(session).get(run.source_id)
            if source is not None:
                await SourceRepository(session).touch_checked(source)
            await session.commit()
