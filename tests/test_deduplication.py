import pytest
import asyncio
from app.services.deduplication import DeduplicationService
from app.core.config import get_settings

settings = get_settings()

@pytest.mark.asyncio
async def test_redis_deduplication():
    # Note: This requires a running Redis instance as configured in .env
    # In a real CI environment, we would mock this or use a test container.
    service = DeduplicationService()
    
    event_id = "test-event-123"
    
    # First time: should NOT be duplicate
    is_dup1 = await service.is_duplicate(event_id, ttl=10)
    assert is_dup1 is False
    
    # Second time: SHOULD be duplicate
    is_dup2 = await service.is_duplicate(event_id, ttl=10)
    assert is_dup2 is True
    
    await service.close()
