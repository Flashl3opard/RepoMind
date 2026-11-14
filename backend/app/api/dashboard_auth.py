"""Simple bearer-token auth applied to every route except /webhooks/github and
/health (the webhook has its own HMAC signature check; health checks need to stay
reachable for orchestration). If DASHBOARD_API_KEY isn't configured, only requests
from localhost are allowed instead -- meant for local dev only.
"""

import hmac
import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

EXEMPT_PATHS = {"/webhooks/github", "/health"}
_LOCALHOST_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}


def warn_if_dashboard_api_key_unset(settings: Settings | None = None) -> None:
    """Call once at startup. Not part of the per-request check itself."""
    settings = settings or get_settings()
    if not settings.DASHBOARD_API_KEY:
        logger.warning(
            "DASHBOARD_API_KEY is not set: only requests from localhost will be accepted. "
            "Set DASHBOARD_API_KEY before deploying this somewhere reachable from the internet."
        )


def is_authorized(authorization_header: str | None, client_host: str | None, settings: Settings) -> bool:
    if settings.DASHBOARD_API_KEY:
        expected = f"Bearer {settings.DASHBOARD_API_KEY}"
        return hmac.compare_digest(authorization_header or "", expected)
    return client_host in _LOCALHOST_HOSTS


class DashboardAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path in EXEMPT_PATHS:
            return await call_next(request)

        settings = get_settings()
        client_host = request.client.host if request.client else None
        if not is_authorized(request.headers.get("authorization"), client_host, settings):
            return JSONResponse({"detail": "unauthorized"}, status_code=401)

        return await call_next(request)
