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
    
    actor_id = actor.get("id")
    room_token = target.get("id")

    # 1. Ignore if bot message to prevent loops
    if actor_id == settings.NEXTCLOUD_BOT_USERNAME:
        return {"status": "ignored"}

    # 2. Filter by Room (Only process if it's the bridged room)
    if room_token != settings.NEXTCLOUD_BRIDGE_ROOM_TOKEN:
        return {"status": "ignored"}

    # 3. Deduplication (Use data.id as primary event ID per Florian's feedback)
    event_id = data.get("id") or obj.get("id")
    if not event_id:
        return {"status": "ignored"}

    if await dedup.is_duplicate(event_id):
        logger.info(f"Duplicate Nextcloud event {event_id} ignored")
        return {"status": "ignored"}

    # 3. Handle Message or File Notification
    if event_type in ["Create", "Activity"] and obj.get("type") == "Note":
        content_raw = obj.get("content", "")
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
                handle_nextcloud_message_task, actor_id, room_token, text, dedup
            )

    # 4. Handle Direct File Uploads (if they don't come as a Note)
    elif event_type in ["Create", "Activity"] and obj.get("type") != "Note":
        file_name = obj.get("name", "Unknown File")
        # For direct Create events, link might be in a different place, 
        # but usually it's in the Activity Note. Fallback to empty if not found.
        file_link = obj.get("link", "")
        background_tasks.add_task(
            handle_nextcloud_file_task, actor_id, room_token, file_name, file_link, dedup
        )
    
    elif event_type in ["Create", "Activity"]:
        logger.info(f"Ignored {event_type} event of type: {obj.get('type')} content: {obj.get('content')}")

    return {"status": "ok"}


async def handle_nextcloud_message_task(actor_id: str, room_token: str, text: str, dedup: DeduplicationService):
    from app.main import async_session

    async with async_session() as session:
        bridge = BridgeService(session, dedup)
        await bridge.handle_nextcloud_message(actor_id, room_token, text)


async def handle_nextcloud_file_task(actor_id: str, room_token: str, file_name: str, file_link: str, dedup: DeduplicationService):
    from app.main import async_session

    async with async_session() as session:
        bridge = BridgeService(session, dedup)
        await bridge.handle_nextcloud_file(actor_id, room_token, file_name, file_link)
