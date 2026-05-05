import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.models.db import Base
from app.core.config import get_settings

settings = get_settings()


@pytest_asyncio.fixture
async def db_session():
    # Use a test database if possible, but for MVP we use the configured one
    # WARNING: This will clear the database!
    engine = create_async_engine(settings.DATABASE_URL)
    async_session = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async with async_session() as session:
        yield session

    await engine.dispose()
