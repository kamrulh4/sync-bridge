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
    from app.core.config import get_settings
    settings = get_settings()
    data = await request.json()

    # 1. Handle Slack URL verification
    if data.get("type") == "url_verification":
        return {"challenge": data.get("challenge")}

    event = data.get("event", {})
    event_id = data.get("event_id")

    # 2. Ignore bot messages to prevent loops
    if event.get("bot_id") or event.get("user") == settings.SLACK_BOT_USER_ID:
        return {"ok": True}

    # 3. Filter by Channel (Dynamic Routing)
    # For reaction events, channel is inside event.item.channel
    item = event.get("item", {})
    channel = event.get("channel") or event.get("channel_id") or item.get("channel")
    from app.services.mapping import MappingService
    from app.models.db import MappingType
    from app.core.database import async_session
    
    is_mapped = False
    if channel == settings.SLACK_BRIDGE_CHANNEL_ID:
        is_mapped = True
    else:
        async with async_session() as session:
            nc_token = await MappingService.get_internal_id(session, channel, MappingType.CHANNEL)
            if nc_token:
                is_mapped = True

    if not is_mapped:
        return {"ok": True}

    # 4. Deduplication
    if await dedup.is_duplicate(event_id):
        logger.info(f"Duplicate Slack event {event_id} ignored")
        return {"ok": True}

    # 4. Handle Message Event
    if event.get("type") == "message" and not event.get("subtype"):
        text = event.get("text")
        user = event.get("user")
        ts = event.get("ts")

        background_tasks.add_task(handle_slack_message_task, user, channel, text, ts, dedup)

    # 5. Handle File Event
    elif event.get("type") == "file_shared":
        file_id = event.get("file_id")
        user_id = event.get("user_id")
        channel_id = event.get("channel_id")

        background_tasks.add_task(
            handle_slack_file_task, file_id, user_id, channel_id, dedup
        )

    # 6. Handle Reaction Events
    elif event.get("type") in ["reaction_added", "reaction_removed"]:
        reaction = event.get("reaction")
        user_id = event.get("user")
        item = event.get("item", {})
        
        if item.get("type") == "message":
            slack_ts = item.get("ts")
            channel_id = item.get("channel")
            action = "add" if event["type"] == "reaction_added" else "remove"
            
            background_tasks.add_task(
                handle_slack_reaction_task, user_id, channel_id, slack_ts, reaction, action, dedup
            )

    return {"ok": True}


async def handle_slack_message_task(user: str, channel: str, text: str, ts: str, dedup: DeduplicationService):
    from app.core.database import async_session

    async with async_session() as session:
        bridge = BridgeService(session, dedup)
        await bridge.handle_slack_message(user, channel, text, ts)


async def handle_slack_file_task(file_id: str, user_id: str, channel_id: str, dedup: DeduplicationService):
    from app.core.database import async_session

    async with async_session() as session:
        bridge = BridgeService(session, dedup)
        await bridge.handle_slack_file(file_id, user_id, channel_id)


async def handle_slack_reaction_task(
    user_id: str, channel_id: str, slack_ts: str, reaction: str, action: str, dedup: DeduplicationService
):
    from app.core.database import async_session

    async with async_session() as session:
        bridge = BridgeService(session, dedup)
        await bridge.handle_slack_reaction(user_id, channel_id, slack_ts, reaction, action)
