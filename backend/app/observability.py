"""Minimal observability: structured JSON logging with a request id correlating every
log line to the request that produced it, plus one structured log line per PR review
run (repo, PR, context mode, latency, finding counts, token estimate -- counts only,
never the diff text, a finding's message, or any credential). LangSmith tracing is a
separate, fully optional opt-in via env (see configure_langsmith_tracing), off by
default.

Nothing here replaces app-level secret handling -- cloner.py/poster.py/auth.py already
never pass a token through anything that gets logged; this module's own log lines are
reviewed the same way, see log_review_run's docstring for exactly what it emits.
"""

import contextvars
import json
import logging
import os
import sys
import time
import uuid
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.config import Settings

_request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)


def get_request_id() -> str | None:
    return _request_id_var.get()


class JsonLogFormatter(logging.Formatter):
    """One JSON object per line. Extra structured fields are passed via
    `logger.info(msg, extra={"extra_fields": {...}})` -- the nested-dict wrapper
    avoids colliding with logging's own reserved LogRecord attribute names (e.g. a
    field literally named "message" or "name" would otherwise raise)."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = get_request_id()
        if request_id:
            payload["request_id"] = request_id
        extra_fields = getattr(record, "extra_fields", None)
        if extra_fields:
            payload.update(extra_fields)
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: int = logging.INFO) -> None:
    """Call once at process startup. Replaces the root logger's handlers so every
    `logging.getLogger(...)` call in the app (and its libraries) emits JSON lines on
    stdout instead of default plain-text formatting."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonLogFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Assigns a request id (from an inbound `X-Request-ID` header, or a fresh one)
    to a contextvar for the duration of the request, echoes it back in the response
    header, and logs one line per request with method/path/status/duration. Register
    this outermost (last `add_middleware` call) so even a request rejected by auth
    still gets an id and a logged outcome."""

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        token = _request_id_var.set(request_id)
        start = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            _request_id_var.reset(token)
        duration_ms = round((time.perf_counter() - start) * 1000, 1)
        response.headers["x-request-id"] = request_id
        logging.getLogger("app.request").info(
            "request completed",
            extra={
                "extra_fields": {
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                }
            },
        )
        return response


def log_review_run(
    *,
    repo: str | None,
    pr_number: int | None,
    mode: str,
    latency_seconds: float,
    finding_count: int,
    estimated_tokens: int,
    status: str,
) -> None:
    """The one structured log line per PR review run (webhook or manual). Emits only
    counts, timing, and identifiers already public on GitHub (repo full_name, PR
    number) -- never the diff text, a finding's message/evidence, or any token/API
    key. `estimated_tokens` is the same chars/4 heuristic used elsewhere in this
    codebase (app.review.context_retrieval.estimate_tokens), a relative signal, not a
    real cost figure."""
    logging.getLogger("app.review").info(
        "review run completed",
        extra={
            "extra_fields": {
                "repo": repo,
                "pr_number": pr_number,
                "mode": mode,
                "latency_seconds": round(latency_seconds, 3),
                "finding_count": finding_count,
                "estimated_tokens": estimated_tokens,
                "status": status,
            }
        },
    )


def configure_langsmith_tracing(settings: Settings) -> None:
    """Off by default. LangSmith tracing is a standard LangChain/LangGraph feature
    toggled by plain process env vars (LANGCHAIN_TRACING_V2 etc.), read directly by
    the langsmith SDK -- not by anything in this app. Since pydantic-settings loading
    backend/.env does NOT itself export those values into os.environ, this function
    does that explicitly when LANGCHAIN_TRACING_V2 is set, so putting them in .env is
    enough rather than also needing to export them in the shell."""
    if not settings.LANGCHAIN_TRACING_V2:
        return
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_PROJECT"] = settings.LANGCHAIN_PROJECT
    if settings.LANGCHAIN_API_KEY:
        os.environ["LANGCHAIN_API_KEY"] = settings.LANGCHAIN_API_KEY
    if settings.LANGCHAIN_ENDPOINT:
        os.environ["LANGCHAIN_ENDPOINT"] = settings.LANGCHAIN_ENDPOINT
    logging.getLogger("app.startup").info(
        "LangSmith tracing enabled", extra={"extra_fields": {"project": settings.LANGCHAIN_PROJECT}}
    )
