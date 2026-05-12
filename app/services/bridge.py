import httpx
import re
import emoji
from app.core.config import get_settings
from app.models.db import MappingType
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.mapping import MappingService
import logging

settings = get_settings()
logger = logging.getLogger(__name__)


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

    async def post_to_nextcloud(self, room_token: str, message: str):
        """Posts a message to Nextcloud Talk room."""
        url = f"{settings.NEXTCLOUD_URL}/ocs/v2.php/apps/spreed/api/v1/chat/{room_token}"
        auth = (settings.NEXTCLOUD_BOT_USERNAME, settings.NEXTCLOUD_BOT_PASSWORD)

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                auth=auth,
                json={"message": message},
                headers={"OCS-APIRequest": "true"},
            )
            if response.status_code != 201:
                logger.error(f"Failed to post to Nextcloud: {response.text}")

    async def post_to_slack(self, channel_id: str, message: str):
        """Posts a message to Slack channel."""
        url = "https://slack.com/api/chat.postMessage"
        headers = {"Authorization": f"Bearer {settings.SLACK_BOT_TOKEN}"}

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url, headers=headers, json={"channel": channel_id, "text": message}
            )
            data = response.json()
            if not data.get("ok"):
                logger.error(f"Failed to post to Slack: {data.get('error')}")

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
        self, slack_user_id: str, channel_id: str, text: str
    ):
        """Processes a message from Slack and sends to Nextcloud."""
        if channel_id != settings.SLACK_BRIDGE_CHANNEL_ID:
            return

        # 1. Resolve Display Name
        nc_username = await MappingService.get_internal_id(
            self.session, slack_user_id, MappingType.USER
        )
        display_name = nc_username or slack_user_id

        # 2. Emoji Conversion
        text = self.convert_emojis(text)

        # 3. Mention Translation
        text = await self.translate_slack_mentions(text)

        # 4. Format as requested: Name (via Slack): Message
        formatted_message = f"{display_name} (via Slack): {text}"
        
        # 5. Deduplication: Mark this formatted message so we don't process it when it comes back
        await self.dedup.is_content_duplicate(formatted_message)
        
        await self.post_to_nextcloud(settings.NEXTCLOUD_BRIDGE_ROOM_TOKEN, formatted_message)

    async def handle_nextcloud_message(
        self, nc_actor_id: str, room_token: str, text: str
    ):
        """Processes a message from Nextcloud and sends to Slack."""
        # 1. Deduplication: If this exact text was recently sent FROM Slack, ignore it
        if await self.dedup.is_content_duplicate(text):
            logger.info(f"Ignoring loopback message from Nextcloud: {text[:50]}...")
            return

        if room_token != settings.NEXTCLOUD_BRIDGE_ROOM_TOKEN:
            return

        username = nc_actor_id.replace("users/", "")
        
        # Resolve Slack Identity for naming
        slack_user_id = await MappingService.get_external_id(
            self.session, username, MappingType.USER
        )
        
        # 2. Format as requested: Name (via Nextcloud): Message
        formatted_message = f"{username} (via Nextcloud): {text}"
        
        # 3. Deduplication: Mark this outgoing message too
        await self.dedup.is_content_duplicate(formatted_message)
        
        await self.post_to_slack(settings.SLACK_BRIDGE_CHANNEL_ID, formatted_message)
