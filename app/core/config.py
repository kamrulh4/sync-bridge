from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    # Slack Configuration
    SLACK_SIGNING_SECRET: str
    SLACK_BOT_TOKEN: str
    SLACK_BRIDGE_CHANNEL_ID: str
    SLACK_FILE_SINK_CHANNEL_ID: str
    SLACK_BOT_USER_ID: str | None = None

    # Nextcloud Configuration
    NEXTCLOUD_URL: str
    NEXTCLOUD_BOT_USERNAME: str
    NEXTCLOUD_BOT_PASSWORD: str
    NEXTCLOUD_BRIDGE_ROOM_TOKEN: str
    NEXTCLOUD_FILE_SINK_ROOM_TOKEN: str

    # Security
    SHARED_HMAC_SECRET: str

    # Database & Redis
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@db:5432/bridge"
    REDIS_URL: str = "redis://redis:6379/0"

    # App Settings
    LOG_LEVEL: str = "INFO"
    DEBUG: bool = False

    model_config = SettingsConfigDict(env_file=".env")


@lru_cache()
def get_settings():
    return Settings()
