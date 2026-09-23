from collections.abc import AsyncGenerator
import os

os.environ.setdefault("AI_ENABLED", "false")
os.environ["TELEGRAM_ENABLED"] = "false"

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.base import Base


async def _drop_test_schema(conn) -> None:
    await conn.run_sync(Base.metadata.drop_all)
    await conn.execute(text("DROP TABLE IF EXISTS alembic_version"))


@pytest.fixture
async def session_factory() -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    test_database_url = os.getenv("TEST_DATABASE_URL")
    if test_database_url:
        engine = create_async_engine(test_database_url)
    else:
        engine = create_async_engine(
            "sqlite+aiosqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    async with engine.begin() as conn:
        await _drop_test_schema(conn)
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await _drop_test_schema(conn)
    await engine.dispose()


@pytest.fixture
async def session(session_factory) -> AsyncGenerator[AsyncSession, None]:
    async with session_factory() as db_session:
        yield db_session


@pytest.fixture
async def file_session_factory(tmp_path) -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    test_database_url = os.getenv("TEST_DATABASE_URL")
    if test_database_url:
        engine = create_async_engine(test_database_url)
    else:
        db_path = tmp_path / "concurrency.sqlite"
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as conn:
        await _drop_test_schema(conn)
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await _drop_test_schema(conn)
    await engine.dispose()
