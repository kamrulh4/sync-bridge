import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.core.security import verify_slack_signature, verify_nextcloud_signature

# Mocking security for integration tests
app.dependency_overrides[verify_slack_signature] = lambda: None
app.dependency_overrides[verify_nextcloud_signature] = lambda: None

@pytest.mark.asyncio
async def test_health_check():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}

@pytest.mark.asyncio
async def test_slack_url_verification():
    payload = {
        "type": "url_verification",
        "challenge": "test_challenge_123"
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.post("/slack/events", json=payload)
    assert response.status_code == 200
    assert response.json() == {"challenge": "test_challenge_123"}

@pytest.mark.asyncio
async def test_slack_message_ignored_if_bot():
    payload = {
        "type": "event_callback",
        "event": {
            "type": "message",
            "bot_id": "B123",
            "text": "Hello from bot"
        }
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.post("/slack/events", json=payload)
    assert response.status_code == 200
    assert response.json() == {"ok": True}

@pytest.mark.asyncio
async def test_nextcloud_webhook_basic():
    import time
    unique_id = f"msg_{int(time.time() * 1000)}"
    payload = {
        "type": "Create",
        "actor": {"id": "users/admin"},
        "object": {"type": "Note", "id": unique_id, "content": "Hi"},
        "target": {"id": "room_1"}
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.post("/nextcloud/webhook", json=payload)
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
