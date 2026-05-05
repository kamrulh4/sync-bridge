from fastapi import APIRouter, Request, Depends, BackgroundTasks
from app.core.security import verify_slack_signature
from app.services.deduplication import get_dedup_service, DeduplicationService
from app.services.bridge import BridgeService
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.db import Base
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

# Note: Dependency injection for DB session would be added here in a real app
# For MVP, we'll assume a session management helper is available.


@router.post("/events")
async def slack_events(
    request: Request,
    background_tasks: BackgroundTasks,
    verify: None = Depends(verify_slack_signature),
    dedup: DeduplicationService = Depends(get_dedup_service),
):
    data = await request.json()
    logger.info(f"Received Slack event: {data.get('type')}")

    # 1. Handle Slack URL verification
    if data.get("type") == "url_verification":
        return {"challenge": data.get("challenge")}

    event = data.get("event", {})
    event_id = data.get("event_id")

    # 2. Ignore bot messages to prevent loops
    if event.get("bot_id"):
        return {"ok": True}

    # 3. Deduplication
    if await dedup.is_duplicate(event_id):
        logger.info(f"Duplicate Slack event {event_id} ignored")
        return {"ok": True}

    # 4. Handle Message Event
    if event.get("type") == "message" and not event.get("subtype"):
        text = event.get("text")
        user = event.get("user")
        channel = event.get("channel")

        from app.main import async_session

        async with async_session() as session:
            bridge = BridgeService(session)
            background_tasks.add_task(bridge.handle_slack_message, user, channel, text)

    # 5. Handle File Event
    elif event.get("type") == "file_shared":
        file_id = event.get("file_id")
        user_id = event.get("user_id")
        channel_id = event.get("channel_id")

        from app.main import async_session

        async with async_session() as session:
            bridge = BridgeService(session)
            background_tasks.add_task(
                bridge.handle_slack_file, file_id, user_id, channel_id
            )

    return {"ok": True}
