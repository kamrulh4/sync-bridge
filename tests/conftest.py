import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.models.db import Base
from app.core.config import get_settings

settings = get_settings()


@pytest_asyncio.fixture
async def db_session():
    # Enforce safe test database usage to prevent dropping production data
    db_url = settings.TEST_DATABASE_URL
    if not db_url:
        # Automatically derive a safe test database URL (e.g. bridge_test) if not explicitly set
        base_url = settings.DATABASE_URL
        if "postgresql" in base_url:
            if base_url.endswith("/bridge"):
                db_url = base_url + "_test"
            else:
                parts = base_url.rsplit("/", 1)
                db_url = f"{parts[0]}/{parts[1]}_test"
        else:
            db_url = base_url

    # CRITICAL SAFETY LOCK: Enforce that the database URL must contain "test" in its name
    if "test" not in db_url.lower():
        raise RuntimeError(
            f"TEST SUITE SAFETY LOCK TRIGGERED!\n"
            f"Configured database URL is: '{db_url}'\n"
            f"It does NOT contain the word 'test' in its name. Running tests would DROP all tables in a production-like database.\n"
            f"Please specify a dedicated test database (e.g. postgresql+asyncpg://.../bridge_test) in your .env or set TEST_DATABASE_URL."
        )

    engine = create_async_engine(db_url)
    async_session = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async with async_session() as session:
        yield session

    await engine.dispose()
