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

    async def translate_slack_mentions(self, text: str) -> str:
        """Translates <@U123> to @username or @U123 based on mapping."""
        mention_pattern = r"<@([A-Z0-9]+)>"
        mentions = re.findall(mention_pattern, text)

        for slack_id in mentions:
            nc_username = await MappingService.get_internal_id(
                self.session, slack_id, MappingType.USER
            )
            replacement = f"@{nc_username}" if nc_username else f"@{slack_id}"
            text = text.replace(f"<@{slack_id}>", replacement)
        return text

    async def post_to_nextcloud(self, room_token: str, message: str) -> str | None:
        """Posts a message to Nextcloud Talk room and returns message ID."""
        url = f"{settings.NEXTCLOUD_URL}/ocs/v2.php/apps/spreed/api/v1/chat/{room_token}"
        auth = (settings.NEXTCLOUD_BOT_USERNAME, settings.NEXTCLOUD_BOT_PASSWORD)

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                auth=auth,
                json={"message": message},
                headers={"OCS-APIRequest": "true"},
            )
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

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url, headers=headers, json={"channel": channel_id, "text": message}
            )
            data = response.json()
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
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, params=params)
            data = response.json()
            return data.get("file", {}) if data.get("ok") else {}

    async def handle_slack_file(self, file_id: str, user_id: str, channel_id: str):
        """Routes Slack file event to the SLACK FILE SINK channel."""
        target_channel = settings.SLACK_FILE_SINK_CHANNEL_ID
        
        file_info = await self.get_slack_file_info(file_id)
        file_name = file_info.get("name", "Unknown File")
        file_link = file_info.get("permalink", "")
        
        # Resolve username if possible
        username = await MappingService.get_internal_id(self.session, user_id, MappingType.USER)
        display_name = username or user_id
        
        message = f"📁 *File Uploaded*: {file_name}\n*User*: {display_name}\n*Link*: {file_link}"
        
        await self.post_to_slack(target_channel, message)

    async def handle_nextcloud_file(
        self, actor_id: str, room_token: str, file_name: str, file_link: str = ""
    ):
        """Routes Nextcloud file event to the NEXTCLOUD FILE SINK room."""
        target_room = settings.NEXTCLOUD_FILE_SINK_ROOM_TOKEN
        username = actor_id.replace("users/", "")
        
        message = f"📁 File Shared: {file_name}\nUser: {username}\nLink: {file_link}"
        
        await self.post_to_nextcloud(target_room, message)

    async def handle_slack_message(
        self, slack_user_id: str, channel_id: str, text: str, slack_ts: str
    ):
        """Processes a message from Slack and sends to Nextcloud."""
        # 1. Resolve Target Room (Dynamic Routing)
        nc_room_token = await MappingService.get_internal_id(
            self.session, channel_id, MappingType.CHANNEL
        )
        if not nc_room_token:
            # Fallback to single bridge if defined (backward compatibility)
            if channel_id == settings.SLACK_BRIDGE_CHANNEL_ID:
                nc_room_token = settings.NEXTCLOUD_BRIDGE_ROOM_TOKEN
            else:
                return

        # 2. Resolve Display Name
        nc_username = await MappingService.get_internal_id(
            self.session, slack_user_id, MappingType.USER
        )
        display_name = nc_username or slack_user_id

        # 3. Emoji Conversion
        text = self.convert_emojis(text)

        # 4. Mention Translation
        text = await self.translate_slack_mentions(text)

        # 5. Format: Name (via Slack): Message
        formatted_message = f"{display_name} (via Slack): {text}"
        
        # 6. Deduplication: Mark this formatted message
        await self.dedup.is_content_duplicate(formatted_message)
        
        # 7. Post and Save Mapping
        nc_msg_id = await self.post_to_nextcloud(nc_room_token, formatted_message)
        if nc_msg_id:
            await MappingService.save_message_mapping(
                self.session, slack_ts, nc_msg_id, channel_id
            )
            # Log success
            self.session.add(AuditLog(source="slack", event_id=slack_ts, content=text[:255], status="success"))
        else:
            self.session.add(AuditLog(source="slack", event_id=slack_ts, content=text[:255], status="failed"))
        
        await self.session.commit()

    async def handle_nextcloud_message(
        self, nc_actor_id: str, room_token: str, text: str, nc_msg_id: str
    ):
        """Processes a message from Nextcloud and sends to Slack."""
        # 1. Deduplication: If this exact text was recently sent FROM Slack, ignore it
        if await self.dedup.is_content_duplicate(text):
            logger.info(f"Ignoring loopback message from Nextcloud: {text[:50]}...")
            return

        # 2. Resolve Target Channel (Dynamic Routing)
        slack_channel_id = await MappingService.get_external_id(
            self.session, room_token, MappingType.CHANNEL
        )
        if not slack_channel_id:
            # Fallback to single bridge if defined
            if room_token == settings.NEXTCLOUD_BRIDGE_ROOM_TOKEN:
                slack_channel_id = settings.SLACK_BRIDGE_CHANNEL_ID
            else:
                return

        username = nc_actor_id.replace("users/", "")
        
        # Resolve Slack Identity for naming
        slack_user_id = await MappingService.get_external_id(
            self.session, username, MappingType.USER
        )
        
        # 3. Format: Name (via Nextcloud): Message
        formatted_message = f"{username} (via Nextcloud): {text}"
        
        # 4. Deduplication: Mark this outgoing message too
        await self.dedup.is_content_duplicate(formatted_message)
        
        # 5. Post and Save Mapping
        slack_ts = await self.post_to_slack(slack_channel_id, formatted_message)
        if slack_ts:
            await MappingService.save_message_mapping(
                self.session, slack_ts, nc_msg_id, room_token
            )
            # Log success
            self.session.add(AuditLog(source="nextcloud", event_id=nc_msg_id, content=text[:255], status="success"))
        else:
            self.session.add(AuditLog(source="nextcloud", event_id=nc_msg_id, content=text[:255], status="failed"))
            
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
        url = f"{settings.NEXTCLOUD_URL}/ocs/v2.php/apps/spreed/api/v1/chat/{nc_room_token}/reaction"
        auth = (settings.NEXTCLOUD_BOT_USERNAME, settings.NEXTCLOUD_BOT_PASSWORD)
        
        async with httpx.AsyncClient() as client:
            if action == "add":
                response = await client.post(
                    url, auth=auth, json={"messageId": int(talk_msg_id), "reaction": nc_reaction},
                    headers={"OCS-APIRequest": "true"}
                )
            else: # remove
                response = await client.request(
                    "DELETE", url, auth=auth, json={"messageId": int(talk_msg_id), "reaction": nc_reaction},
                    headers={"OCS-APIRequest": "true"}
                )
            
            if response.status_code not in [200, 201, 204]:
                logger.error(f"Failed to sync reaction to Nextcloud: {response.text}")

    async def handle_nextcloud_reaction(
        self, room_token: str, nc_msg_id: str, emoji_char: str, action: str
    ):
        """Syncs a reaction from Nextcloud to Slack."""
        # 1. Resolve Target Channel
        slack_channel_id = await MappingService.get_external_id(
            self.session, room_token, MappingType.CHANNEL
        )
        if not slack_channel_id:
            if room_token == settings.NEXTCLOUD_BRIDGE_ROOM_TOKEN:
                slack_channel_id = settings.SLACK_BRIDGE_CHANNEL_ID
            else:
                return

        # 2. Map Reaction
        slack_reaction = NC_TO_SLACK_REACTION.get(emoji_char)
        if not slack_reaction:
            # Fallback: try to get name from emoji unicode
            import emoji as emoji_lib
            name = emoji_lib.demojize(emoji_char).replace(":", "")
            slack_reaction = name

        # 3. Lookup Slack TS
        slack_ts = await MappingService.get_slack_ts_by_talk_id(self.session, nc_msg_id)
        if not slack_ts:
            logger.warning(f"Could not find Slack message for Nextcloud ID {nc_msg_id}")
            return

        # 4. Sync to Slack
        url = f"https://slack.com/api/reactions.{'add' if action == 'add' else 'remove'}"
        headers = {"Authorization": f"Bearer {settings.SLACK_BOT_TOKEN}"}
        payload = {
            "channel": slack_channel_id,
            "name": slack_reaction,
            "timestamp": slack_ts
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=payload)
            data = response.json()
            if not data.get("ok"):
                # "already_reacted" is common and can be ignored
                if data.get("error") not in ["already_reacted", "no_reaction"]:
                    logger.error(f"Failed to sync reaction to Slack: {data.get('error')}")
