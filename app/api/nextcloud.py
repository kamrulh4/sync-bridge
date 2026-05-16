from fastapi import APIRouter, Request, Depends, BackgroundTasks
from app.core.security import verify_nextcloud_signature
from app.services.bridge import BridgeService
from app.services.deduplication import get_dedup_service, DeduplicationService
from app.core.config import get_settings
import logging
import json

settings = get_settings()
router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/webhook")
async def nextcloud_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    verify: None = Depends(verify_nextcloud_signature),
    dedup: DeduplicationService = Depends(get_dedup_service),
):
    data = await request.json()

    # Activity Streams 2.0 format
    event_type = data.get("type")
    actor = data.get("actor", {})
    obj = data.get("object", {})
    target = data.get("target", {})
    
    actor_id = actor.get("id", "").replace("users/", "")
    room_token = target.get("id")

    # 1. Ignore if bot message to prevent loops
    if actor_id == settings.NEXTCLOUD_BOT_USERNAME:
        return {"status": "ignored"}

    # 2. Filter by Room (Dynamic Routing)
    from app.services.mapping import MappingService
    from app.models.db import MappingType
    from app.core.database import async_session
    
    is_mapped = False
    if room_token == settings.NEXTCLOUD_BRIDGE_ROOM_TOKEN:
        is_mapped = True
    else:
        async with async_session() as session:
            slack_channel = await MappingService.get_external_id(session, room_token, MappingType.CHANNEL)
            if slack_channel:
                is_mapped = True

    if not is_mapped:
        return {"status": "ignored"}

    # 3. Deduplication (Use data.id as primary event ID per Florian's feedback)
    event_id = data.get("id") or obj.get("id")
    if not event_id:
        return {"status": "ignored"}

    if await dedup.is_duplicate(event_id):
        logger.info(f"Duplicate Nextcloud event {event_id} ignored")
        return {"status": "ignored"}

    # 4. Handle Reaction Events (Nextcloud Talk specific types)
    elif (event_type in ["Create", "Activity", "Reaction"] and obj.get("type") == "Reaction") or data.get("verb") == "react":
        emoji_char = obj.get("content", "")
        # For reactions, Nextcloud usually puts the parent message ID in obj.target.id or similar
        nc_msg_id = obj.get("target", {}).get("id") or obj.get("id") # Fallback
        
        if emoji_char and nc_msg_id:
            action = "remove" if event_type == "Undo" else "add"
            background_tasks.add_task(
                handle_nextcloud_reaction_task, room_token, nc_msg_id, emoji_char, action, dedup
            )

    # 5. Handle Message or File Notification
    elif event_type in ["Create", "Activity"] and obj.get("type") == "Note":
        # Filter out system notes like reactions or other auto-messages
        if obj.get("name") in ["reaction_added", "reaction_revoked", "system_message"]:
            logger.info(f"Ignoring system note: {obj.get('name')}")
            return {"status": "ignored"}

        content_raw = obj.get("content", "")
        
        # Filter out Nextcloud system messages (e.g. "[actor] reacted...")
        if "[actor]" in content_raw:
            logger.info(f"Ignoring Nextcloud system message: {content_raw}")
            return {"status": "ignored"}

        try:
            text = json.loads(content_raw).get("message", content_raw)
        except Exception:
            text = content_raw

        if text == "{file}":
            params = json.loads(content_raw).get("parameters", {})
            file_info = params.get("file", {})
            file_name = file_info.get("name", "Unknown File")
            file_link = file_info.get("link", "")
            background_tasks.add_task(
                handle_nextcloud_file_task, actor_id, room_token, file_name, file_link, dedup
            )
        else:
            background_tasks.add_task(
                handle_nextcloud_message_task, actor_id, room_token, text, obj.get("id"), dedup
            )

    # 5. Handle Direct File Uploads (if they don't come as a Note)
    elif event_type in ["Create", "Activity"] and obj.get("type") != "Note":
        file_name = obj.get("name", "Unknown File")
        # For direct Create events, link might be in a different place
        file_link = obj.get("link", "")
        background_tasks.add_task(
            handle_nextcloud_file_task, actor_id, room_token, file_name, file_link, dedup
        )
    
    elif event_type in ["Create", "Activity"]:
        logger.info(f"Ignored {event_type} event of type: {obj.get('type')} content: {obj.get('content')}")

    return {"status": "ok"}


async def handle_nextcloud_message_task(actor_id: str, room_token: str, text: str, nc_msg_id: str, dedup: DeduplicationService):
    from app.core.database import async_session

    async with async_session() as session:
        bridge = BridgeService(session, dedup)
        await bridge.handle_nextcloud_message(actor_id, room_token, text, nc_msg_id)


async def handle_nextcloud_file_task(actor_id: str, room_token: str, file_name: str, file_link: str, dedup: DeduplicationService):
    from app.core.database import async_session

    async with async_session() as session:
        bridge = BridgeService(session, dedup)
        await bridge.handle_nextcloud_file(actor_id, room_token, file_name, file_link)


async def handle_nextcloud_reaction_task(
    room_token: str, nc_msg_id: str, emoji_char: str, action: str, dedup: DeduplicationService
):
    from app.core.database import async_session

    async with async_session() as session:
        bridge = BridgeService(session, dedup)
        await bridge.handle_nextcloud_reaction(room_token, nc_msg_id, emoji_char, action)
