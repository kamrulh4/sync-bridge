import httpx
import re
import emoji
from app.core.config import get_settings
from app.models.db import MappingType, AuditLog
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.mapping import MappingService
import logging

settings = get_settings()
logger = logging.getLogger(__name__)

SLACK_TO_NC_REACTION = {
    "thumbsup": "👍",
    "+1": "👍",
    "thumbsdown": "👎",
    "-1": "👎",
    "white_check_mark": "✅",
    "heart": "❤️",
    "pray": "🙏",
    "joy": "😂",
    "eyes": "👀",
    "heavy_check_mark": "✔️",
    "muscle": "💪",
    "question": "❓",
    "exclamation": "❗",
}

NC_TO_SLACK_REACTION = {
    "👍": "thumbsup",
    "👎": "thumbsdown",
    "✅": "white_check_mark",
    "❤️": "heart",
    "🙏": "pray",
    "😂": "joy",
    "👀": "eyes",
    "✔️": "heavy_check_mark",
    "💪": "muscle",
    "❓": "question",
    "❗": "exclamation",
}


class BridgeService:
    def __init__(self, session: AsyncSession, dedup_service):
        self.session = session
        self.dedup = dedup_service

    def convert_emojis(self, text: str) -> str:
        """Converts Slack shortcodes to Unicode emojis."""
        return emoji.emojize(text, language="alias")

    async def get_slack_user_display_name(self, slack_user_id: str) -> str:
        """Fetches Slack user display name for a fallback when mapping is missing."""
        if not slack_user_id:
            return slack_user_id

        url = "https://slack.com/api/users.info"
        headers = {"Authorization": f"Bearer {settings.SLACK_BOT_TOKEN}"}
        params = {"user": slack_user_id}

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, params=params)
            data = response.json()
            if data.get("ok"):
                user = data.get("user", {})
                profile = user.get("profile", {})
                return profile.get("display_name") or profile.get("real_name") or slack_user_id

        return slack_user_id

    async def translate_slack_mentions(self, text: str) -> str:
        """Translates <@U123> to @username or @U123 based on mapping."""
        mention_pattern = r"<@([A-Z0-9]+)>"
        mentions = re.findall(mention_pattern, text)

        for slack_id in mentions:
            nc_username = await MappingService.get_internal_id(
                self.session, slack_id, MappingType.USER
            )
            if nc_username:
                replacement = f"@{nc_username}"
            else:
                slack_name = await self.get_slack_user_display_name(slack_id)
                replacement = f"@{slack_name}" if slack_name else f"@{slack_id}"
            text = text.replace(f"<@{slack_id}>", replacement)
        return text

    async def post_to_nextcloud(self, room_token: str, message: str) -> str | None:
        """Posts a message to Nextcloud Talk room and returns message ID."""
        url = f"{settings.NEXTCLOUD_URL}/ocs/v2.php/apps/spreed/api/v1/chat/{room_token}?format=json"
        auth = (settings.NEXTCLOUD_BOT_USERNAME, settings.NEXTCLOUD_BOT_PASSWORD)
        logger.info(f"Posting to Nextcloud: room={room_token} message={message}")

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                auth=auth,
                json={"message": message},
                headers={"OCS-APIRequest": "true"},
            )
            logger.info(f"Nextcloud response: status={response.status_code} body={response.text}")
            if response.status_code == 201:
                data = response.json()
                # Nextcloud Talk OCS API returns message ID in the response body
                return data.get("ocs", {}).get("data", {}).get("id")
            else:
                logger.error(f"Failed to post to Nextcloud: {response.text}")
                return None

    async def post_to_slack(self, channel_id: str, message: str) -> str | None:
        """Posts a message to Slack channel and returns timestamp."""
        url = "https://slack.com/api/chat.postMessage"
        headers = {"Authorization": f"Bearer {settings.SLACK_BOT_TOKEN}"}
        logger.info(f"Posting to Slack: channel={channel_id} message={message}")

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url, headers=headers, json={"channel": channel_id, "text": message}
            )
            data = response.json()
            logger.info(f"Slack response: {data}")
            if data.get("ok"):
                return data.get("ts")
            else:
                logger.error(f"Failed to post to Slack: {data.get('error')}")
                return None

    async def get_slack_file_info(self, file_id: str) -> dict:
        """Fetches file info from Slack."""
        url = "https://slack.com/api/files.info"
        headers = {"Authorization": f"Bearer {settings.SLACK_BOT_TOKEN}"}
        params = {"file": file_id}
        logger.info(f"Fetching Slack file info: file_id={file_id}")
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, params=params)
            data = response.json()
            logger.info(f"Slack files.info response: {data}")
            return data.get("file", {}) if data.get("ok") else {}

    async def handle_slack_file(self, file_id: str, user_id: str, channel_id: str):
        """Routes Slack file event to the NEXTCLOUD FILE SINK room."""
        logger.info(f"Handling Slack file event: file_id={file_id} user_id={user_id} channel_id={channel_id}")
        target_room = await MappingService.get_internal_id(
            self.session, "talk", MappingType.FILE_SINK
        ) or settings.NEXTCLOUD_FILE_SINK_ROOM_TOKEN

        file_info = await self.get_slack_file_info(file_id)
        file_name = file_info.get("name", "Unknown File")
        file_link = (
            file_info.get("permalink")
            or file_info.get("permalink_public")
            or file_info.get("url_private_download")
            or file_info.get("url_private")
            or ""
        )

        username = await MappingService.get_internal_id(self.session, user_id, MappingType.USER)
        display_name = username or user_id
        logger.info(f"Slack file details: name={file_name} link={file_link} display_name={display_name} target_room={target_room}")

        message = (
            f"📁 *File Uploaded from Slack*: {file_name}\n"
            f"*User*: {display_name}\n"
            f"*Link*: {file_link or 'No link available'}"
        )

        await self.post_to_nextcloud(target_room, message)

    async def handle_nextcloud_file(
        self, actor_id: str, room_token: str, file_name: str, file_link: str = ""
    ):
        """Routes Nextcloud file event to the SLACK FILE SINK channel."""
        logger.info(f"Handling Nextcloud file event: actor={actor_id} room={room_token} file_name={file_name} file_link={file_link}")
        target_channel = await MappingService.get_internal_id(
            self.session, "slack", MappingType.FILE_SINK
        ) or settings.SLACK_FILE_SINK_CHANNEL_ID
        username = actor_id.replace("users/", "")

        message = (
            f"📁 *File Shared from Nextcloud*: {file_name}\n"
            f"*User*: {username}\n"
            f"*Link*: {file_link or 'No link available'}"
        )

        await self.post_to_slack(target_channel, message)

    async def handle_slack_message(
        self, slack_user_id: str, channel_id: str, text: str, slack_ts: str
    ):
        """Processes a message from Slack and sends to Nextcloud."""
        logger.info(f"Handling Slack message: slack_user_id={slack_user_id} channel_id={channel_id} slack_ts={slack_ts} text={text}")
        nc_room_token = await MappingService.get_internal_id(
            self.session, channel_id, MappingType.CHANNEL
        )
        if not nc_room_token:
            if channel_id == settings.SLACK_BRIDGE_CHANNEL_ID:
                nc_room_token = settings.NEXTCLOUD_BRIDGE_ROOM_TOKEN
            else:
                logger.info(f"Slack message ignored: channel {channel_id} not mapped")
                return

        nc_username = await MappingService.get_internal_id(
            self.session, slack_user_id, MappingType.USER
        )
        if nc_username:
            display_name = nc_username
        else:
            display_name = await self.get_slack_user_display_name(slack_user_id)

        text = text or ""
        text = self.convert_emojis(text)
        text = await self.translate_slack_mentions(text)

        # Check if this message was recently bridged from Nextcloud (race condition & loopback protection)
        nc_dedup_key = f"nextcloud:{nc_room_token}:{text}"
        if await self.dedup.is_content_duplicate(nc_dedup_key):
            logger.info(f"Skipping loopback message from Nextcloud: {text[:80]}")
            return

        # Also, if the text contains " via Nextcloud]: ", ignore it as a loopback
        if " via Nextcloud]: " in text:
            logger.info(f"Skipping bot loopback message from Nextcloud: {text[:80]}")
            return

        formatted_message = f"[{display_name} via Slack]: {text}"
        logger.info(f"Formatted Slack->Nextcloud message: {formatted_message}")

        dedup_key = f"slack:{nc_room_token}:{formatted_message}"
        if await self.dedup.is_content_duplicate(dedup_key):
            logger.info(f"Skipping duplicate Slack message to Nextcloud: {formatted_message[:80]}")
            return

        nc_msg_id = await self.post_to_nextcloud(nc_room_token, formatted_message)
        if nc_msg_id:
            await MappingService.save_message_mapping(
                self.session, slack_ts, nc_msg_id, channel_id
            )
            self.session.add(
                AuditLog(source="slack", event_id=slack_ts, content=formatted_message[:255], status="success")
            )
            logger.info(f"Slack message successfully posted to Nextcloud: talk_msg_id={nc_msg_id}")
        else:
            self.session.add(
                AuditLog(source="slack", event_id=slack_ts, content=formatted_message[:255], status="failed")
            )
            logger.error("Slack->Nextcloud post failed")

        await self.session.commit()

    async def handle_nextcloud_message(
        self, nc_actor_id: str, room_token: str, text: str, nc_msg_id: str
    ):
        """Processes a message from Nextcloud and sends to Slack."""
        username = nc_actor_id.replace("users/", "")
        formatted_message = f"[{username} via Nextcloud]: {text}"
        logger.info(f"Handling Nextcloud message: actor={nc_actor_id} room={room_token} nc_msg_id={nc_msg_id} text={text}")

        dedup_key = f"nextcloud:{room_token}:{formatted_message}"
        if await self.dedup.is_content_duplicate(dedup_key):
            logger.info(f"Ignoring loopback message from Nextcloud: {formatted_message[:80]}...")
            return

        slack_channel_id = await MappingService.get_external_id(
            self.session, room_token, MappingType.CHANNEL
        )
        if not slack_channel_id:
            if room_token == settings.NEXTCLOUD_BRIDGE_ROOM_TOKEN:
                slack_channel_id = settings.SLACK_BRIDGE_CHANNEL_ID
            else:
                logger.info(f"Nextcloud message ignored: room {room_token} not mapped to Slack")
                return

        slack_ts = await self.post_to_slack(slack_channel_id, formatted_message)
        if slack_ts:
            await MappingService.save_message_mapping(
                self.session, slack_ts, nc_msg_id, room_token
            )
            self.session.add(
                AuditLog(source="nextcloud", event_id=nc_msg_id, content=formatted_message[:255], status="success")
            )
            logger.info(f"Nextcloud message successfully posted to Slack: slack_ts={slack_ts}")
        else:
            self.session.add(
                AuditLog(source="nextcloud", event_id=nc_msg_id, content=formatted_message[:255], status="failed")
            )
            logger.error("Nextcloud->Slack post failed")

        await self.session.commit()

    async def handle_slack_reaction(
        self, slack_user_id: str, channel_id: str, slack_ts: str, reaction_name: str, action: str
    ):
        """Syncs a reaction from Slack to Nextcloud."""
        # 1. Resolve Target Room
        nc_room_token = await MappingService.get_internal_id(
            self.session, channel_id, MappingType.CHANNEL
        )
        if not nc_room_token:
            if channel_id == settings.SLACK_BRIDGE_CHANNEL_ID:
                nc_room_token = settings.NEXTCLOUD_BRIDGE_ROOM_TOKEN
            else:
                return

        # 2. Map Reaction
        nc_reaction = SLACK_TO_NC_REACTION.get(reaction_name)
        if not nc_reaction:
            # Fallback: try to see if it's already an emoji or use it as is if it matches a known unicode
            nc_reaction = emoji.emojize(f":{reaction_name}:", language="alias")
            if nc_reaction == f":{reaction_name}:": # If not found
                return

        # 3. Lookup Message ID
        talk_msg_id = await MappingService.get_talk_id_by_slack_ts(self.session, slack_ts)
        if not talk_msg_id:
            logger.warning(f"Could not find Nextcloud message for Slack TS {slack_ts}")
            return

        # 4. Sync to Nextcloud
        url = f"{settings.NEXTCLOUD_URL}/ocs/v2.php/apps/spreed/api/v1/reaction/{nc_room_token}/{talk_msg_id}?format=json"
        auth = (settings.NEXTCLOUD_BOT_USERNAME, settings.NEXTCLOUD_BOT_PASSWORD)
        
        # Store reaction dedup key to prevent Nextcloud webhook from echoing it back
        reaction_dedup_key = f"reaction:nc:{nc_room_token}:{talk_msg_id}:{nc_reaction}"
        await self.dedup.is_content_duplicate(reaction_dedup_key, ttl=60)

        async with httpx.AsyncClient() as client:
            try:
                if action == "add":
                    response = await client.post(
                        url, auth=auth, json={"reaction": nc_reaction},
                        headers={"OCS-APIRequest": "true"}
                    )
                else: # remove
                    response = await client.request(
                        "DELETE", url, auth=auth, json={"reaction": nc_reaction},
                        headers={"OCS-APIRequest": "true"}
                    )
                
                if response.status_code not in [200, 201, 204]:
                    logger.error(f"Failed to sync reaction to Nextcloud: status={response.status_code} body={response.text}")
                else:
                    logger.info(f"Successfully synced reaction {nc_reaction} ({action}) to Nextcloud msg {talk_msg_id}")
            except Exception as e:
                logger.error(f"Error calling Nextcloud reaction API: {str(e)}")

    async def handle_nextcloud_reaction(
        self, room_token: str, nc_msg_id: str, emoji_char: str, action: str
    ):
        """Syncs a reaction from Nextcloud to Slack."""
        slack_channel_id = await MappingService.get_external_id(
            self.session, room_token, MappingType.CHANNEL
        )
        if not slack_channel_id:
            if room_token == settings.NEXTCLOUD_BRIDGE_ROOM_TOKEN:
                slack_channel_id = settings.SLACK_BRIDGE_CHANNEL_ID
            else:
                return

        slack_reaction = NC_TO_SLACK_REACTION.get(emoji_char)
        if not slack_reaction:
            import emoji as emoji_lib
            name = emoji_lib.demojize(emoji_char).replace(":", "")
            slack_reaction = name

        slack_ts = await MappingService.get_slack_ts_by_talk_id(self.session, nc_msg_id)
        if not slack_ts:
            logger.warning(f"Could not find Slack message for Nextcloud ID {nc_msg_id}")
            return

        url = f"https://slack.com/api/reactions.{'add' if action == 'add' else 'remove'}"
        headers = {"Authorization": f"Bearer {settings.SLACK_BOT_TOKEN}"}
        payload = {
            "channel": slack_channel_id,
            "name": slack_reaction,
            "timestamp": slack_ts,
        }

        logger.info(f"Syncing reaction to Slack: channel={slack_channel_id} slack_ts={slack_ts} reaction={slack_reaction} action={action}")
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, headers=headers, json=payload)
                data = response.json()
                logger.info(f"Slack reactions API response: {data}")
                if not data.get("ok"):
                    if data.get("error") not in ["already_reacted", "no_reaction"]:
                        logger.error(f"Failed to sync reaction to Slack: {data.get('error')}")
                else:
                    logger.info(f"Successfully synced reaction {slack_reaction} ({action}) to Slack ts {slack_ts}")
            except Exception as e:
                logger.error(f"Error calling Slack reaction API: {str(e)}")
