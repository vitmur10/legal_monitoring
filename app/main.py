from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes.documents import router as documents_router
from app.api.routes.health import router as health_router
from app.api.routes.monitoring import router as monitoring_router
from app.api.routes.review import router as review_router
from app.api.routes.sources import router as sources_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import AsyncSessionLocal
from app.monitoring.scheduler import MonitoringScheduler
from app.sources.dps import DpsAdapter
from app.sources.minfin import MinfinAdapter
from app.sources.mock import MockSourceAdapter
from app.sources.rada import RadaAdapter
from app.sources.registry import registry
from app.sources.zir import ZirAdapter


settings = get_settings()
configure_logging(settings.log_level)
registry.register(MockSourceAdapter())
registry.register(RadaAdapter())
registry.register(DpsAdapter())
registry.register(MinfinAdapter())
registry.register(ZirAdapter())


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler: MonitoringScheduler | None = None
    if settings.scheduler_enabled:
        scheduler = MonitoringScheduler(AsyncSessionLocal, registry)
        await scheduler.start()
    yield
    if scheduler is not None:
        scheduler.shutdown()


app = FastAPI(title="Legal Monitoring MVP", version="0.1.0", lifespan=lifespan)
app.include_router(health_router)
app.include_router(sources_router)
app.include_router(monitoring_router)
app.include_router(documents_router)
app.include_router(review_router)
