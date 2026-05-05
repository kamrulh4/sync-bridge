import hmac
import hashlib
import time
import logging
from fastapi import Request, HTTPException, Depends
from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


async def verify_slack_signature(request: Request):
    """
    Verifies the signature of a Slack request.
    """
    timestamp = request.headers.get("X-Slack-Request-Timestamp")
    signature = request.headers.get("X-Slack-Signature")

    if not timestamp or not signature:
        raise HTTPException(status_code=401, detail="Missing Slack signature headers")

    # Prevent replay attacks
    if abs(time.time() - int(timestamp)) > 60 * 5:
        raise HTTPException(status_code=401, detail="Slack request timestamp too old")

    body = await request.body()
    sig_basestring = f"v0:{timestamp}:{body.decode('utf-8')}"

    my_signature = f"v0={hmac.new(
        settings.SLACK_SIGNING_SECRET.encode(),
        sig_basestring.encode(),
        hashlib.sha256
    ).hexdigest()}"

    if not hmac.compare_digest(my_signature, signature):
        logger.error(f"Slack signature verification failed. Sig: {signature}")
        raise HTTPException(status_code=401, detail="Invalid Slack signature")


async def verify_nextcloud_signature(request: Request):
    """
    Verifies the signature of a Nextcloud Talk request.
    Nextcloud signs using: HMAC-SHA256(RandomString + Body, SharedSecret)
    """
    random_str = request.headers.get("X-Nextcloud-Talk-Random")
    signature = request.headers.get("X-Nextcloud-Talk-Signature")

    if not random_str or not signature:
        raise HTTPException(
            status_code=401, detail="Missing Nextcloud signature headers"
        )

    body = await request.body()
    payload = random_str.encode() + body

    my_signature = hmac.new(
        settings.SHARED_HMAC_SECRET.encode(), payload, hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(my_signature, signature.lower()):
        logger.error(f"Nextcloud signature verification failed. Sig: {signature}")
        raise HTTPException(status_code=401, detail="Invalid Nextcloud signature")
