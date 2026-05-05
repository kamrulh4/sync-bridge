import asyncio
import sys
import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.core.config import get_settings
from app.services.mapping import MappingService
from app.models.db import MappingType

settings = get_settings()


async def main():
    if len(sys.argv) < 3:
        print(
            "Usage: python scripts/import_mappings.py <type: user|channel> <file_path>"
        )
        return

    m_type_str = sys.argv[1].lower()
    file_path = sys.argv[2]

    if m_type_str == "user":
        m_type = MappingType.USER
    elif m_type_str == "channel":
        m_type = MappingType.CHANNEL
    else:
        print("Invalid mapping type. Use 'user' or 'channel'.")
        return

    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        return

    engine = create_async_engine(settings.DATABASE_URL)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        with open(file_path, "r") as f:
            content = f.read()
            await MappingService.import_from_csv(session, content, m_type)
        print(f"Imported {m_type_str} mappings from {file_path}")


if __name__ == "__main__":
    asyncio.run(main())
