from fastapi import FastAPI, Request
from app.api import slack, nextcloud, mappings
from app.core.config import get_settings
from app.models.db import Base
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
import logging

settings = get_settings()

# Setup logging
logging.basicConfig(level=getattr(logging, settings.LOG_LEVEL))
logger = logging.getLogger(__name__)

from app.core.database import engine, async_session

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Create tables (In production, use migrations)
    from sqlalchemy import text
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Auto-patch DB schema for new thread mapping columns if they don't exist
        await conn.execute(text("ALTER TABLE message_mappings ADD COLUMN IF NOT EXISTS parent_slack_ts VARCHAR(50);"))
        await conn.execute(text("ALTER TABLE message_mappings ADD COLUMN IF NOT EXISTS parent_talk_id VARCHAR(50);"))

    if settings.AUTO_IMPORT_MAPPINGS:
        from pathlib import Path
        from app.services.mapping import MappingService
        from app.models.db import MappingType

        repo_root = Path(__file__).resolve().parent.parent
        mapping_files = {
            MappingType.USER: repo_root / "user_mapping.csv",
            MappingType.CHANNEL: repo_root / "channel_mapping.csv",
            MappingType.FILE_SINK: repo_root / "filesink_mapping.csv",
        }

        async with async_session() as session:
            for m_type, path in mapping_files.items():
                if path.exists():
                    content = path.read_text(encoding="utf-8")
                    imported = await MappingService.import_from_csv(session, content, m_type)
                    logger.info(f"Imported {imported} {m_type.value} mappings from {path.name}")

    # Initialize Deduplication Service
    from app.services.deduplication import DeduplicationService
    app.state.dedup = DeduplicationService()

    logger.info("Database tables created and Redis initialized.")
    yield
    # Shutdown: Close Redis
    await app.state.dedup.close()

app = FastAPI(title="Nextcloud-Slack Bridge", version="1.0.0", lifespan=lifespan)

@app.middleware("http")
async def log_requests(request: Request, call_next):
    body = await request.body()
    logger.info(f"DEBUG: Incoming Request: {request.method} {request.url}")
    logger.info(f"DEBUG: Headers: {dict(request.headers)}")
    if body:
        logger.info(f"DEBUG: Body: {body.decode('utf-8', errors='ignore')}")
    async def receive():
        return {"type": "http.request", "body": body}
    request._receive = receive
    response = await call_next(request)
    logger.info(f"DEBUG: Response: status_code={response.status_code} url={request.url}")
    return response

# Register Routes
app.include_router(slack.router, prefix="/slack", tags=["slack"])
app.include_router(nextcloud.router, prefix="/nextcloud", tags=["nextcloud"])
app.include_router(mappings.router, prefix="/mapping", tags=["mapping"])


@app.get("/health")
async def health():
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
