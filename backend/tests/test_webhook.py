import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

import app.github_app.service as service_module
from app.config import get_settings
from app.github_app.webhook import verify_signature
from app.main import app

WEBHOOK_SECRET = "test-webhook-secret"


def sign(body: bytes, secret: str = WEBHOOK_SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def pr_payload(action="opened", draft=False, number=1, head_sha="sha-abc", fork=False) -> dict:
    head_full_name = "forker/repo" if fork else "owner/repo"
    return {
        "action": action,
        "pull_request": {
            "number": number,
            "draft": draft,
            "head": {"sha": head_sha, "repo": {"full_name": head_full_name}},
        },
        "repository": {
            "full_name": "owner/repo",
            "clone_url": "https://github.com/owner/repo.git",
            "default_branch": "main",
        },
        "installation": {"id": 555},
    }


# -- pure signature verification (no DB, no client needed) ----------------------------


def test_verify_signature_accepts_correct_signature():
    body = b'{"a": 1}'
    assert verify_signature(body, sign(body), WEBHOOK_SECRET)


def test_verify_signature_rejects_wrong_secret():
    body = b'{"a": 1}'
    assert not verify_signature(body, sign(body, secret="wrong-secret"), WEBHOOK_SECRET)


def test_verify_signature_rejects_tampered_body():
    body = b'{"a": 1}'
    signature = sign(body)
    assert not verify_signature(b'{"a": 2}', signature, WEBHOOK_SECRET)


def test_verify_signature_rejects_missing_header():
    assert not verify_signature(b"{}", None, WEBHOOK_SECRET)


def test_verify_signature_rejects_malformed_header():
    assert not verify_signature(b"{}", "not-a-real-signature", WEBHOOK_SECRET)


# -- TestClient-based webhook tests -----------------------------------------------------


@pytest.fixture
def client(monkeypatch, db_session) -> TestClient:
    monkeypatch.setattr(service_module, "SessionLocal", sessionmaker(bind=db_session.get_bind()))
    monkeypatch.setattr(service_module, "process_pull_request_review", lambda *a, **k: None)

    settings = get_settings()
    monkeypatch.setattr(settings, "GITHUB_WEBHOOK_SECRET", WEBHOOK_SECRET)
    monkeypatch.setattr(settings, "GITHUB_REVIEW_FORKS", False)

    return TestClient(app)


def post_webhook(client: TestClient, event: str, payload: dict, secret: str | None = WEBHOOK_SECRET):
    body = json.dumps(payload).encode("utf-8")
    headers = {"X-GitHub-Event": event, "Content-Type": "application/json"}
    if secret is not None:
        headers["X-Hub-Signature-256"] = sign(body, secret)
    return client.post("/webhooks/github", content=body, headers=headers)


def test_ping_event_returns_200_without_touching_db(client):
    response = post_webhook(client, "ping", {"zen": "hello"})
    assert response.status_code == 200
    assert response.json()["status"] == "pong"


def test_valid_signature_is_accepted_and_queues_a_run(client):
    response = post_webhook(client, "pull_request", pr_payload())
    assert response.status_code == 200
    assert response.json()["status"] == "queued"


def test_missing_signature_is_rejected_with_401(client):
    response = post_webhook(client, "pull_request", pr_payload(), secret=None)
    assert response.status_code == 401


def test_invalid_signature_is_rejected_with_401(client):
    body = json.dumps(pr_payload()).encode("utf-8")
    response = client.post(
        "/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-Hub-Signature-256": "sha256=0000000000000000000000000000000000000000000000000000000000000000",
        },
    )
    assert response.status_code == 401


def test_duplicate_delivery_is_a_no_op(client):
    payload = pr_payload(number=42, head_sha="same-sha")
    first = post_webhook(client, "pull_request", payload)
    second = post_webhook(client, "pull_request", payload)

    assert first.json()["status"] == "queued"
    assert second.json()["status"] == "duplicate"
    assert first.json()["run_id"] == second.json()["run_id"]


def test_draft_pr_is_skipped(client):
    response = post_webhook(client, "pull_request", pr_payload(draft=True))
    assert response.status_code == 200
    assert response.json()["status"] == "skipped"
    assert "draft" in response.json()["reason"]


def test_fork_pr_is_skipped_by_default(client):
    response = post_webhook(client, "pull_request", pr_payload(fork=True))
    assert response.status_code == 200
    assert response.json()["status"] == "skipped"
    assert "fork" in response.json()["reason"]


def test_unhandled_pull_request_action_is_ignored(client):
    response = post_webhook(client, "pull_request", pr_payload(action="closed"))
    assert response.status_code == 200
    assert response.json()["status"] == "skipped"


def test_unknown_event_type_is_ignored_with_200(client):
    response = post_webhook(client, "deployment", {"foo": "bar"})
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"
