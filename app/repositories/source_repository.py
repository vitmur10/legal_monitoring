from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.source import Source


class SourceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, source_id: int) -> Source | None:
        return await self.session.get(Source, source_id)

    async def get_by_code(self, code: str) -> Source | None:
        result = await self.session.execute(select(Source).where(Source.code == code))
        return result.scalar_one_or_none()

    async def list(self, enabled: bool | None = None) -> list[Source]:
        query = select(Source).order_by(Source.code)
        if enabled is not None:
            query = query.where(Source.enabled.is_(enabled))
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def touch_checked(self, source: Source) -> None:
        source.last_checked_at = datetime.now(timezone.utc)
