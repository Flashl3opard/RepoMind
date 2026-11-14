import json
import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.observability import (
    JsonLogFormatter,
    RequestIdMiddleware,
    configure_langsmith_tracing,
    get_request_id,
    log_review_run,
)

# -- JsonLogFormatter -------------------------------------------------------------------


def make_record(msg="hello", extra_fields=None) -> logging.LogRecord:
    record = logging.LogRecord(name="app.test", level=logging.INFO, pathname="", lineno=0, msg=msg, args=(), exc_info=None)
    if extra_fields is not None:
        record.extra_fields = extra_fields
    return record


def test_json_log_formatter_produces_valid_json():
    formatted = JsonLogFormatter().format(make_record())
    payload = json.loads(formatted)
    assert payload["message"] == "hello"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "app.test"


def test_json_log_formatter_includes_extra_fields():
    formatted = JsonLogFormatter().format(make_record(extra_fields={"repo": "owner/repo", "finding_count": 3}))
    payload = json.loads(formatted)
    assert payload["repo"] == "owner/repo"
    assert payload["finding_count"] == 3


def test_json_log_formatter_omits_request_id_when_none_set():
    formatted = JsonLogFormatter().format(make_record())
    assert "request_id" not in json.loads(formatted)


def test_json_log_formatter_never_crashes_on_non_json_serializable_extra():
    # default=str in json.dumps means this must not raise, even for odd types.
    formatted = JsonLogFormatter().format(make_record(extra_fields={"value": object()}))
    assert json.loads(formatted)["value"].startswith("<object")


# -- RequestIdMiddleware ----------------------------------------------------------------


def make_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)

    @app.get("/ping")
    def ping():
        return {"request_id_seen_inside_handler": get_request_id()}

    return app


def test_request_id_middleware_generates_id_and_echoes_header():
    client = TestClient(make_app())
    response = client.get("/ping")
    assert response.status_code == 200
    assert "x-request-id" in response.headers
    assert response.json()["request_id_seen_inside_handler"] == response.headers["x-request-id"]


def test_request_id_middleware_reuses_incoming_header():
    client = TestClient(make_app())
    response = client.get("/ping", headers={"X-Request-ID": "my-custom-id"})
    assert response.headers["x-request-id"] == "my-custom-id"
    assert response.json()["request_id_seen_inside_handler"] == "my-custom-id"


def test_request_id_middleware_generates_different_ids_per_request():
    client = TestClient(make_app())
    first = client.get("/ping").headers["x-request-id"]
    second = client.get("/ping").headers["x-request-id"]
    assert first != second


def test_get_request_id_is_none_outside_a_request():
    assert get_request_id() is None


# -- log_review_run -----------------------------------------------------------------------


def test_log_review_run_emits_structured_fields_without_diff_or_message_content(caplog):
    with caplog.at_level(logging.INFO, logger="app.review"):
        log_review_run(
            repo="owner/repo", pr_number=42, mode="full", latency_seconds=1.234,
            finding_count=2, estimated_tokens=500, status="completed",
        )
    record = caplog.records[0]
    assert record.extra_fields == {
        "repo": "owner/repo", "pr_number": 42, "mode": "full",
        "latency_seconds": 1.234, "finding_count": 2, "estimated_tokens": 500, "status": "completed",
    }
    # the log call itself never takes diff text or finding message content as input,
    # so there's nothing in extra_fields beyond these seven counters/identifiers.
    assert set(record.extra_fields) == {
        "repo", "pr_number", "mode", "latency_seconds", "finding_count", "estimated_tokens", "status",
    }


# -- configure_langsmith_tracing ---------------------------------------------------------


def test_langsmith_tracing_disabled_by_default_does_not_touch_environ(monkeypatch):
    monkeypatch.delenv("LANGCHAIN_TRACING_V2", raising=False)
    settings = Settings(LANGCHAIN_TRACING_V2=False)
    configure_langsmith_tracing(settings)
    assert "LANGCHAIN_TRACING_V2" not in __import__("os").environ


def test_langsmith_tracing_enabled_exports_env_vars(monkeypatch):
    monkeypatch.delenv("LANGCHAIN_TRACING_V2", raising=False)
    monkeypatch.delenv("LANGCHAIN_API_KEY", raising=False)
    settings = Settings(LANGCHAIN_TRACING_V2=True, LANGCHAIN_API_KEY="ls-key", LANGCHAIN_PROJECT="my-project")
    configure_langsmith_tracing(settings)

    import os

    assert os.environ["LANGCHAIN_TRACING_V2"] == "true"
    assert os.environ["LANGCHAIN_API_KEY"] == "ls-key"
    assert os.environ["LANGCHAIN_PROJECT"] == "my-project"

    monkeypatch.delenv("LANGCHAIN_TRACING_V2", raising=False)
    monkeypatch.delenv("LANGCHAIN_API_KEY", raising=False)
    monkeypatch.delenv("LANGCHAIN_PROJECT", raising=False)
