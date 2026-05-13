import httpx
import asyncio
from app.core.config import get_settings

async def get_bot_id():
    settings = get_settings()
    url = "https://slack.com/api/auth.test"
    headers = {"Authorization": f"Bearer {settings.SLACK_BOT_TOKEN}"}
    
    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers=headers)
        data = response.json()
        if data.get("ok"):
            print(f"Bot User ID: {data.get('user_id')}")
            print(f"Bot Name: {data.get('user')}")
        else:
            print(f"Error: {data.get('error')}")

if __name__ == "__main__":
    asyncio.run(get_bot_id())
