from fastapi import APIRouter, Request, Depends, BackgroundTasks
from app.core.security import verify_nextcloud_signature
from app.services.bridge import BridgeService
from app.services.deduplication import get_dedup_service, DeduplicationService
from app.core.config import get_settings
import logging

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

    event_id = obj.get("id")

    # 1. Ignore if no message id
    if not event_id:
        return {"status": "ignored"}

    # 2. Deduplication
    if await dedup.is_duplicate(event_id):
        logger.info(f"Duplicate Nextcloud event {event_id} ignored")
        return {"status": "ignored"}

    actor_id = actor.get("id")
    room_token = target.get("id")

    # 3. Handle Message
    if event_type == "Create" and obj.get("type") == "Note":
        import json
        content_raw = obj.get("content", "")
        try:
            text = json.loads(content_raw).get("message", content_raw)
        except Exception:
            text = content_raw

        if text == "{file}":
            params = json.loads(content_raw).get("parameters", {})
            file_info = params.get("file", {})
            file_name = file_info.get("name", "Unknown File")
            background_tasks.add_task(
                handle_nextcloud_file_task, actor_id, room_token, file_name
            )
        else:
            background_tasks.add_task(
                handle_nextcloud_message_task, actor_id, room_token, text
            )

    # 4. Handle File (Any Create event that is not a Note is likely a file/attachment)
    elif event_type == "Create" and obj.get("type") != "Note":
        file_name = obj.get("name", "Unknown File")
        background_tasks.add_task(
            handle_nextcloud_file_task, actor_id, room_token, file_name
        )
    
    elif event_type == "Create":
        logger.info(f"Ignored Create event of type: {obj.get('type')} content: {obj.get('content')}")

    return {"status": "ok"}


async def handle_nextcloud_message_task(actor_id: str, room_token: str, text: str):
    from app.main import async_session

    async with async_session() as session:
        bridge = BridgeService(session)
        await bridge.handle_nextcloud_message(actor_id, room_token, text)


async def handle_nextcloud_file_task(actor_id: str, room_token: str, file_name: str):
    from app.main import async_session

    async with async_session() as session:
        bridge = BridgeService(session)
        await bridge.handle_nextcloud_file(actor_id, room_token, file_name)
