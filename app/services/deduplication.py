import redis.asyncio as redis
from app.core.config import get_settings

settings = get_settings()


class DeduplicationService:
    def __init__(self):
        self.redis = redis.from_url(settings.REDIS_URL, decode_responses=True)

    async def is_duplicate(self, event_id: str, ttl: int = 120) -> bool:
        """
        Checks if an event_id has been processed recently.
        Returns True if duplicate, False if new (and marks it as seen).
        """
        key = f"bridge:dedup:{event_id}"
        # setnx (set if not exists)
        is_new = await self.redis.set(key, "1", ex=ttl, nx=True)
        return not is_new

    async def close(self):
        await self.redis.aclose()


dedup_service = DeduplicationService()


def get_dedup_service():
    return dedup_service
