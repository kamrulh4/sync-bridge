from fastapi import FastAPI, Request
from app.api import slack, nextcloud
from app.core.config import get_settings
from app.models.db import Base
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
import logging

settings = get_settings()

# Setup logging
logging.basicConfig(level=getattr(logging, settings.LOG_LEVEL))
logger = logging.getLogger(__name__)

# Database Setup
engine = create_async_engine(settings.DATABASE_URL)
async_session = async_sessionmaker(engine, expire_on_commit=False)

from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Create tables (In production, use migrations)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables created via lifespan.")
    yield


app = FastAPI(title="Nextcloud-Slack Bridge", version="1.0.0", lifespan=lifespan)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    body = await request.body()
    logger.info(f"DEBUG: Incoming Request: {request.method} {request.url}")
    logger.info(f"DEBUG: Headers: {dict(request.headers)}")
    if body:
        logger.info(f"DEBUG: Body: {body.decode('utf-8', errors='ignore')}")

    # Replace body for later handlers
    async def receive():
        return {"type": "http.request", "body": body}

    request._receive = receive

    response = await call_next(request)
    return response


# Register Routes
app.include_router(slack.router, prefix="/slack", tags=["slack"])
app.include_router(nextcloud.router, prefix="/nextcloud", tags=["nextcloud"])


@app.get("/health")
async def health():
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
