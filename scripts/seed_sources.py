import asyncio

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.source import Source


SOURCES = [
    {
        "code": "mock",
        "name": "Mock source",
        "base_url": "https://example.test",
        "enabled": True,
        "check_interval_minutes": 60,
    },
    {
        "code": "rada",
        "name": "Verkhovna Rada of Ukraine",
        "base_url": "https://rada.gov.ua",
        "enabled": False,
        "check_interval_minutes": 60,
    },
    {
        "code": "dps",
        "name": "State Tax Service of Ukraine",
        "base_url": "https://tax.gov.ua",
        "enabled": False,
        "check_interval_minutes": 60,
    },
    {
        "code": "zir",
        "name": "ZIR STS",
        "base_url": "https://zir.tax.gov.ua",
        "enabled": False,
        "check_interval_minutes": 60,
    },
    {
        "code": "minfin",
        "name": "Ministry of Finance of Ukraine",
        "base_url": "https://mof.gov.ua",
        "enabled": False,
        "check_interval_minutes": 60,
    },
]


async def main() -> None:
    async with AsyncSessionLocal() as session:
        for payload in SOURCES:
            result = await session.execute(select(Source).where(Source.code == payload["code"]))
            existing = result.scalar_one_or_none()
            if existing is None:
                session.add(Source(**payload))
            else:
                for key, value in payload.items():
                    setattr(existing, key, value)
        await session.commit()


if __name__ == "__main__":
    asyncio.run(main())
