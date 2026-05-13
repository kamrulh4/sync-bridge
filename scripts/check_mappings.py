import asyncio
from app.main import async_session
from sqlalchemy import select
from app.models.db import Mapping, MappingType

async def check_mappings():
    async with async_session() as session:
        result = await session.execute(select(Mapping))
        mappings = result.scalars().all()
        print(f"Total mappings found: {len(mappings)}")
        for m in mappings:
            print(f"ID: {m.id}, Type: {m.type}, External: {m.external_id}, Internal: {m.internal_id}")

if __name__ == "__main__":
    asyncio.run(check_mappings())
