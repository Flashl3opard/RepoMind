"""Bearer-token auth applied to every route except /webhooks/github (own HMAC
signature check) and /health (needs to stay reachable for orchestration).

Fails closed: if DASHBOARD_API_KEY isn't configured, every protected route returns
503 instead of falling back to a "trust the network" check. A prior version of this
file allowed localhost-only requests when the key was unset; that's unsafe behind any
reverse proxy or tunnel, where every request's observed client address is the proxy's
own, not the original caller's -- so it wasn't actually restricting anything in that
(very common) deployment shape.

DASHBOARD_AUTH_DISABLED=true is an explicit, loud opt-out for local development (e.g.
hitting the API directly without setting up a key). `validate_auth_config` refuses to
start the app with it set if the app can take any real-world-visible action
(REVIEW_DRY_RUN=false, or a webhook secret configured) -- there'd be nothing gating
the blast radius of a review actually posting, or a live webhook being processed,
while every route is open to anyone who can reach the process.
"""

import hmac
import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

EXEMPT_PATHS = {"/webhooks/github", "/health"}


class DashboardAuthConfigError(RuntimeError):
    """Raised at startup when DASHBOARD_AUTH_DISABLED is set alongside settings that
    make disabling auth unsafe."""


def validate_auth_config(settings: Settings | None = None) -> None:
    """Call once at startup. Raises DashboardAuthConfigError to abort startup."""
    settings = settings or get_settings()

    if settings.DASHBOARD_AUTH_DISABLED:
        logger.warning(
            "DASHBOARD_AUTH_DISABLED=true: ALL dashboard API authentication is OFF. "
            "Every route except /webhooks/github and /health is open to anyone who can "
            "reach this process. This is meant for local development only -- never for "
            "a deployment reachable from a network you don't fully trust."
        )
        if not settings.REVIEW_DRY_RUN:
            raise DashboardAuthConfigError(
                "DASHBOARD_AUTH_DISABLED=true requires REVIEW_DRY_RUN=true: refusing to "
                "start with dashboard auth disabled while reviews can actually post to "
                "GitHub."
            )
        if settings.GITHUB_WEBHOOK_SECRET:
            raise DashboardAuthConfigError(
                "DASHBOARD_AUTH_DISABLED=true requires GITHUB_WEBHOOK_SECRET to be "
                "unset: refusing to start with dashboard auth disabled while a live "
                "webhook is configured."
            )
        return

    if not settings.DASHBOARD_API_KEY:
        logger.warning(
            "DASHBOARD_API_KEY is not set: every route except /webhooks/github and "
            "/health will return 503 until it's configured. Set DASHBOARD_API_KEY, or "
            "explicitly set DASHBOARD_AUTH_DISABLED=true for local development."
        )


def is_authorized(authorization_header: str | None, settings: Settings) -> bool:
    """Only meaningful when settings.DASHBOARD_API_KEY is truthy -- callers return 503
    instead of calling this when it isn't configured."""
    expected = f"Bearer {settings.DASHBOARD_API_KEY}"
    return hmac.compare_digest(authorization_header or "", expected)


class DashboardAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path in EXEMPT_PATHS:
            return await call_next(request)

        settings = get_settings()

        if settings.DASHBOARD_AUTH_DISABLED:
            return await call_next(request)

        if not settings.DASHBOARD_API_KEY:
            return JSONResponse({"detail": "DASHBOARD_API_KEY is not configured"}, status_code=503)

        if not is_authorized(request.headers.get("authorization"), settings):
            return JSONResponse({"detail": "unauthorized"}, status_code=401)

        return await call_next(request)
