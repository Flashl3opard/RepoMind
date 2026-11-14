"""GitHub App authentication: short-lived app JWTs (RS256) and cached installation
access tokens. Never logs tokens, keys, or Authorization headers.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import httpx
import jwt

from app.config import Settings, get_settings

JWT_TTL_SECONDS = 9 * 60  # GitHub caps app JWTs at 10 minutes; stay safely under it
TOKEN_EXPIRY_SAFETY_MARGIN_SECONDS = 60  # refresh ~1 min before actual expiry


class Clock(Protocol):
    def now(self) -> float: ...


class SystemClock:
    def now(self) -> float:
        return time.time()


def load_private_key(raw_key_or_path: str) -> str:
    """GITHUB_APP_PRIVATE_KEY may be PEM text directly, or a path to a PEM file."""
    stripped = raw_key_or_path.strip()
    if stripped.startswith("-----BEGIN"):
        return stripped
    return Path(raw_key_or_path).read_text()


def create_app_jwt(app_id: str, private_key_pem: str, now: float | None = None) -> str:
    issued_at = int(now if now is not None else time.time())
    payload = {
        "iat": issued_at - 60,  # tolerate minor clock drift, per GitHub's own guidance
        "exp": issued_at + JWT_TTL_SECONDS,
        "iss": app_id,
    }
    return jwt.encode(payload, private_key_pem, algorithm="RS256")


def _parse_github_timestamp(value: str) -> float:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp()


def _default_token_fetcher(installation_id: int, app_jwt: str, timeout: float) -> dict:
    headers = {"Authorization": f"Bearer {app_jwt}", "Accept": "application/vnd.github+json"}
    url = f"https://api.github.com/app/installations/{installation_id}/access_tokens"
    response = httpx.post(url, headers=headers, timeout=timeout)
    response.raise_for_status()
    return response.json()


@dataclass(slots=True)
class _CachedToken:
    token: str
    expires_at: float


class InstallationTokenProvider:
    """Caches one installation access token per installation_id in memory until
    shortly before it expires. `token_fetcher(installation_id, app_jwt, timeout) ->
    {"token": ..., "expires_at": "2026-...Z"}` is injectable for tests."""

    def __init__(
        self,
        app_id: str,
        private_key_pem: str,
        *,
        clock: Clock | None = None,
        timeout: float = 15.0,
        token_fetcher: Callable[[int, str, float], dict] | None = None,
    ) -> None:
        self._app_id = app_id
        self._private_key_pem = private_key_pem
        self._clock = clock or SystemClock()
        self._timeout = timeout
        self._token_fetcher = token_fetcher or _default_token_fetcher
        self._cache: dict[int, _CachedToken] = {}

    def get_token(self, installation_id: int) -> str:
        now = self._clock.now()
        cached = self._cache.get(installation_id)
        if cached is not None and cached.expires_at - TOKEN_EXPIRY_SAFETY_MARGIN_SECONDS > now:
            return cached.token

        app_jwt = create_app_jwt(self._app_id, self._private_key_pem, now=now)
        data = self._token_fetcher(installation_id, app_jwt, self._timeout)
        token = data["token"]
        expires_at = _parse_github_timestamp(data["expires_at"])
        self._cache[installation_id] = _CachedToken(token=token, expires_at=expires_at)
        return token


def build_installation_token_provider(settings: Settings | None = None) -> InstallationTokenProvider:
    settings = settings or get_settings()
    if not settings.GITHUB_APP_ID or not settings.GITHUB_APP_PRIVATE_KEY:
        raise RuntimeError("GITHUB_APP_ID and GITHUB_APP_PRIVATE_KEY must both be configured")
    private_key = load_private_key(settings.GITHUB_APP_PRIVATE_KEY)
    return InstallationTokenProvider(settings.GITHUB_APP_ID, private_key)


def _default_app_info_fetcher(app_jwt: str, timeout: float) -> dict:
    headers = {"Authorization": f"Bearer {app_jwt}", "Accept": "application/vnd.github+json"}
    response = httpx.get("https://api.github.com/app", headers=headers, timeout=timeout)
    response.raise_for_status()
    return response.json()


class AppIdentityProvider:
    """Resolves and caches the App's own bot login (`"<slug>[bot]"`), via `GET /app`
    authenticated with the app JWT (not an installation token -- this is app-level
    identity, not per-installation). Used to scope comment dedup to comments this app
    actually posted, never to a human who happens to write identical text. The slug
    doesn't change at runtime, so it's cached for the life of the process once fetched.
    """

    def __init__(
        self,
        app_id: str,
        private_key_pem: str,
        *,
        clock: Clock | None = None,
        timeout: float = 15.0,
        app_info_fetcher: Callable[[str, float], dict] | None = None,
    ) -> None:
        self._app_id = app_id
        self._private_key_pem = private_key_pem
        self._clock = clock or SystemClock()
        self._timeout = timeout
        self._app_info_fetcher = app_info_fetcher or _default_app_info_fetcher
        self._bot_login: str | None = None

    def get_bot_login(self) -> str:
        if self._bot_login is None:
            app_jwt = create_app_jwt(self._app_id, self._private_key_pem, now=self._clock.now())
            data = self._app_info_fetcher(app_jwt, self._timeout)
            self._bot_login = f"{data['slug']}[bot]"
        return self._bot_login


def build_app_identity_provider(settings: Settings | None = None) -> AppIdentityProvider:
    settings = settings or get_settings()
    if not settings.GITHUB_APP_ID or not settings.GITHUB_APP_PRIVATE_KEY:
        raise RuntimeError("GITHUB_APP_ID and GITHUB_APP_PRIVATE_KEY must both be configured")
    private_key = load_private_key(settings.GITHUB_APP_PRIVATE_KEY)
    return AppIdentityProvider(settings.GITHUB_APP_ID, private_key)
