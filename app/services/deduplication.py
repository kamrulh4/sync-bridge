import redis.asyncio as redis
from app.core.config import get_settings

settings = get_settings()


class DeduplicationService:
    def __init__(self):
        self.redis = redis.from_url(settings.REDIS_URL, decode_responses=True)

    async def is_duplicate(self, event_id: str, ttl: int = 120) -> bool:
        """Checks if an event_id has been processed recently."""
        key = f"bridge:dedup:{event_id}"
        is_new = await self.redis.set(key, "1", ex=ttl, nx=True)
        return not is_new

    async def is_content_duplicate(self, content: str, ttl: int = 5) -> bool:
        """
        Prevents the exact same text from being bridged back and forth.
        TTL is short (5s) to allow natural repetition but stop instant loops.
        """
        import hashlib
        # Normalize content to avoid whitespace issues
        normalized = content.strip()
        if not normalized:
            return False
            
        h = hashlib.md5(normalized.encode()).hexdigest()
        key = f"bridge:content:{h}"
        is_new = await self.redis.set(key, "1", ex=ttl, nx=True)
        return not is_new

    async def close(self):
        await self.redis.aclose()


dedup_service = DeduplicationService()


def get_dedup_service():
    return dedup_service
