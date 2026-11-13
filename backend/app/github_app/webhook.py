"""POST /webhooks/github -- GitHub App webhook receiver.

Verifies the X-Hub-Signature-256 HMAC-SHA256 signature BEFORE parsing the body
(constant-time comparison), dispatches pull_request/push/ping events, and does all
real work in a background task so the response stays fast and 200s go out quickly.
"""

import hashlib
import hmac
import json
import logging

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request

from app.config import get_settings
from app.github_app import service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["github-app"])


def verify_signature(payload_body: bytes, signature_header: str | None, secret: str) -> bool:
    """Constant-time HMAC-SHA256 verification of GitHub's `X-Hub-Signature-256`."""
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode("utf-8"), payload_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)


@router.post("/webhooks/github")
async def github_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_hub_signature_256: str | None = Header(default=None),
    x_github_event: str | None = Header(default=None),
) -> dict:
    raw_body = await request.body()
    settings = get_settings()

    secret = settings.GITHUB_WEBHOOK_SECRET
    if not secret or not verify_signature(raw_body, x_hub_signature_256, secret):
        raise HTTPException(status_code=401, detail="invalid or missing signature")

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="invalid JSON body") from exc

    if x_github_event == "ping":
        return {"status": "pong"}

    if x_github_event == "pull_request":
        return service.handle_pull_request_webhook(payload, background_tasks, settings)

    if x_github_event == "push":
        return service.handle_push_webhook(payload, background_tasks, settings)

    return {"status": "ignored", "event": x_github_event}
