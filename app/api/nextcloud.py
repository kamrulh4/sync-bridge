from fastapi import APIRouter, Request, Depends, BackgroundTasks
from app.core.security import verify_nextcloud_signature
from app.services.bridge import BridgeService
from app.services.deduplication import get_dedup_service, DeduplicationService
import logging

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
    logger.info(f"Received Nextcloud event: {data.get('type')}")

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

    # 3. Handle Message
    if event_type == "Create" and obj.get("type") == "Note":
        content_raw = obj.get("content", "")
        
        # Nextcloud Talk sends message content as a JSON string in some versions
        try:
            import json
            content_json = json.loads(content_raw)
            text = content_json.get("message", content_raw)
        except (json.JSONDecodeError, TypeError):
            text = content_raw

        actor_id = actor.get("id")
        room_token = target.get("id")

        from app.main import async_session

        async with async_session() as session:
            bridge = BridgeService(session)
            background_tasks.add_task(
                bridge.handle_nextcloud_message, actor_id, room_token, text
            )

    # 4. Handle File (Placeholder for Webhook Listeners or specialized objects)
    elif event_type == "Create" and obj.get("type") in ["Document", "Image", "Video"]:
        file_name = obj.get("name", "Unknown File")
        actor_id = actor.get("id")
        room_token = target.get("id")

        from app.main import async_session

        async with async_session() as session:
            bridge = BridgeService(session)
            background_tasks.add_task(
                bridge.handle_nextcloud_file, actor_id, room_token, file_name
            )

    return {"status": "ok"}
