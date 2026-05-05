import hmac
import hashlib
import time
import pytest
from fastapi import Request
from app.core.security import verify_slack_signature, verify_nextcloud_signature
from app.core.config import get_settings
from fastapi.exceptions import HTTPException

settings = get_settings()


class MockRequest:
    def __init__(self, headers, body):
        self.headers = headers
        self._body = body

    async def body(self):
        return self._body


@pytest.mark.asyncio
async def test_verify_slack_signature_success():
    timestamp = str(int(time.time()))
    body = b'{"type": "url_verification"}'
    sig_basestring = f"v0:{timestamp}:{body.decode('utf-8')}"
    signature = f"v0={hmac.new(
        settings.SLACK_SIGNING_SECRET.encode(),
        sig_basestring.encode(),
        hashlib.sha256
    ).hexdigest()}"

    request = MockRequest(
        {"X-Slack-Request-Timestamp": timestamp, "X-Slack-Signature": signature}, body
    )

    # Should not raise exception
    await verify_slack_signature(request)


@pytest.mark.asyncio
async def test_verify_slack_signature_fail():
    request = MockRequest(
        {"X-Slack-Request-Timestamp": "123", "X-Slack-Signature": "invalid"}, b"body"
    )

    with pytest.raises(HTTPException):
        await verify_slack_signature(request)


@pytest.mark.asyncio
async def test_verify_nextcloud_signature_success():
    random_str = "random123"
    body = b'{"type": "Create"}'
    payload = random_str.encode() + body
    signature = hmac.new(
        settings.SHARED_HMAC_SECRET.encode(), payload, hashlib.sha256
    ).hexdigest()

    request = MockRequest(
        {
            "X-Nextcloud-Talk-Random": random_str,
            "X-Nextcloud-Talk-Signature": signature,
        },
        body,
    )

    # Should not raise exception
    await verify_nextcloud_signature(request)
