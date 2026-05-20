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
    logger.info(f"Nextcloud webhook received: type={data.get('type')} id={data.get('id')} payload={data}")

    # Activity Streams 2.0 format
    event_type = data.get("type")
    actor = data.get("actor", {})
    obj = data.get("object", {})
    target = data.get("target", {})
    
    raw_actor_id = actor.get("id", "")
    actor_id = raw_actor_id.replace("users/", "")
    room_token = target.get("id")
    logger.info(
        f"NC webhook: event_type={event_type}, actor={actor_id}, room={room_token}, obj_type={obj.get('type')}, obj_name={obj.get('name')}"
    )

    bot_actor_ids = {
        settings.NEXTCLOUD_BOT_USERNAME,
        f"users/{settings.NEXTCLOUD_BOT_USERNAME}",
    }
    if settings.NEXTCLOUD_BOT_ACTOR_ID:
        bot_actor_ids.add(settings.NEXTCLOUD_BOT_ACTOR_ID)

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
        logger.info(f"NC webhook: IGNORED (room {room_token} not mapped)")
        return {"status": "ok"}

    # If this event is a message Note that already maps to a Slack message, ignore it as a Slack->Nextcloud loopback.
    # We only apply this to Create/Activity events, not Like/Undo (reactions), because reactions on bridged messages should sync.
    if event_type in ["Create", "Activity"] and obj.get("type") == "Note" and obj.get("id"):
        async with async_session() as session:
            if await MappingService.get_slack_ts_by_talk_id(session, obj.get("id")):
                logger.info(f"NC webhook: IGNORED (loopback Slack message, talk_msg_id={obj.get('id')})")
                return {"status": "ignored"}

    # Ignore bot-generated events from Nextcloud that are not Note, Reaction, Like, or Undo.
    if raw_actor_id in bot_actor_ids and obj.get("type") not in ["Note", "Reaction", "Like"] and event_type not in ["Like", "Undo"]:
        logger.info("NC webhook: IGNORED (bot actor non-note/non-reaction event)")
        return {"status": "ignored"}

    # 3. Deduplication
    event_id = data.get("id") or obj.get("id")
    if not event_id:
        return {"status": "ignored"}

    if await dedup.is_duplicate(event_id):
        logger.info(f"NC webhook: IGNORED (duplicate event_id {event_id})")
        return {"status": "ignored"}

    logger.info(f"NC webhook: PROCESSING event_id={event_id}")

    # --- Route the event ---

    # 4. Handle Reaction Events
    is_reaction = False
    emoji_char = ""
    nc_msg_id = None
    action = "add"

    if event_type == "Like":
        is_reaction = True
        emoji_char = data.get("content", "")
        nc_msg_id = obj.get("id")
        action = "add"
    elif event_type == "Undo" and obj.get("type") == "Like":
        is_reaction = True
        emoji_char = obj.get("content", "")
        target_note = obj.get("object", {})
        nc_msg_id = target_note.get("id") if isinstance(target_note, dict) else target_note
        action = "remove"
    elif obj.get("type") == "Reaction" or data.get("verb") in {"react", "unreact"}:
        is_reaction = True
        emoji_char = obj.get("content", "")
        nc_msg_id = obj.get("target", {}).get("id") or obj.get("id")
        action = "remove" if data.get("verb") == "unreact" or event_type == "Undo" else "add"

    if is_reaction:
        if emoji_char and nc_msg_id:
            reaction_dedup_key = f"reaction:nc:{room_token}:{nc_msg_id}:{emoji_char}"
            if await dedup.is_content_duplicate(reaction_dedup_key):
                logger.info(f"NC webhook: IGNORED (recently bridged reaction from Slack)")
                return {"status": "ignored"}

            background_tasks.add_task(
                handle_nextcloud_reaction_task, room_token, nc_msg_id, emoji_char, action, dedup
            )
        return {"status": "ok"}

    # 5. Handle Message Notification
    elif event_type in ["Create", "Activity"] and obj.get("type") == "Note":
        # Filter out system notes (reaction_added, reaction_revoked, etc.)
        obj_name = obj.get("name", "")
        if obj_name in ["reaction_added", "reaction_revoked", "system_message"]:
            logger.info(f"Ignoring system note: {obj_name}")
            return {"status": "ignored"}

        content_raw = obj.get("content", "")
        
        # Filter out Nextcloud system messages containing {actor} placeholders
        if "{actor}" in content_raw or "[actor]" in content_raw:
            logger.info(f"Ignoring Nextcloud system message: {content_raw[:80]}")
            return {"status": "ignored"}

        try:
            parsed = json.loads(content_raw)
            text = parsed.get("message", content_raw)
            logger.info(f"Parsed Nextcloud note content: message={text} parameters={parsed.get('parameters')}")
        except Exception:
            text = content_raw
            logger.info(f"Nextcloud note content parse failed, raw content={content_raw}")

        # Handle file messages
        if text and text.strip() == "{file}":
            try:
                params = json.loads(content_raw).get("parameters", {})
                file_info = params.get("file", {})
                file_name = file_info.get("name", "Unknown File")
                file_link = file_info.get("link", "")
                logger.info(f"Nextcloud file note detected: file_name={file_name} file_link={file_link}")
                background_tasks.add_task(
                    handle_nextcloud_file_task, actor_id, room_token, file_name, file_link, dedup
                )
            except Exception as exc:
                logger.error(f"Failed to parse Nextcloud file note: {exc}")
            return {"status": "ignored"}

        # Skip empty messages
        if not text or not text.strip():
            logger.info("NC webhook: IGNORED (empty message content)")
            return {"status": "ignored"}

        # Check if this message was recently bridged from Slack (race condition & loopback protection)
        slack_dedup_key = f"slack:{room_token}:{text}"
        if await dedup.is_content_duplicate(slack_dedup_key):
            logger.info(f"NC webhook: IGNORED (recently bridged from Slack, matched dedup key: {slack_dedup_key})")
            return {"status": "ignored"}

        # Also, if the actor is the bot, and the text contains " via Slack]: " or starts with "📁 File Shared: ", ignore it
        if raw_actor_id in bot_actor_ids and (" via Slack]: " in text or text.startswith("📁 File Shared: ")):
            logger.info(f"NC webhook: IGNORED (bot actor loopback message: {text[:80]})")
            return {"status": "ignored"}

        logger.info(f"NC webhook: queuing Nextcloud message task: actor={actor_id} room={room_token} msg_id={obj.get('id')} text={text}")
        background_tasks.add_task(
            handle_nextcloud_message_task, actor_id, room_token, text, obj.get("id"), dedup
        )

    # 6. Handle Direct File Uploads (non-Note objects)
    elif event_type in ["Create", "Activity"] and obj.get("type") not in ["Note", "Reaction"]:
        file_name = obj.get("name", "Unknown File")
        file_link = obj.get("link", "")
        background_tasks.add_task(
            handle_nextcloud_file_task, actor_id, room_token, file_name, file_link, dedup
        )

    else:
        logger.info(f"Unhandled NC event: type={event_type} obj_type={obj.get('type')} obj_name={obj.get('name')}")

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
