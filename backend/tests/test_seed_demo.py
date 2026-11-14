import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from seed_demo import (  # noqa: E402
    ask_sample_questions,
    ingest_repo,
    read_dashboard_api_key_from_root_env,
    run_sample_review,
)


def make_mock_client(handler) -> httpx.Client:
    return httpx.Client(base_url="http://backend.test", transport=httpx.MockTransport(handler))


def test_ingest_repo_polls_until_completed(monkeypatch):
    calls = {"status": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/repos":
            return httpx.Response(202, json={"id": "repo-1", "status": "pending"})
        if request.url.path == "/repos/repo-1":
            calls["status"] += 1
            status = "completed" if calls["status"] >= 2 else "cloning"
            return httpx.Response(
                200,
                json={
                    "id": "repo-1", "url": "https://github.com/a/b", "status": status,
                    "last_commit_sha": "abc" if status == "completed" else None,
                    "error_message": None, "file_count": 3, "chunk_count": 10,
                },
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    monkeypatch.setattr("seed_demo.time.sleep", lambda _: None)
    client = make_mock_client(handler)
    repo_id = ingest_repo(client, "https://github.com/a/b")

    assert repo_id == "repo-1"
    assert calls["status"] == 2


def test_ingest_repo_raises_on_failed_status(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/repos":
            return httpx.Response(202, json={"id": "repo-1", "status": "pending"})
        return httpx.Response(
            200,
            json={
                "id": "repo-1", "url": "https://github.com/a/b", "status": "failed",
                "last_commit_sha": None, "error_message": "clone failed", "file_count": 0, "chunk_count": 0,
            },
        )

    monkeypatch.setattr("seed_demo.time.sleep", lambda _: None)
    client = make_mock_client(handler)

    with pytest.raises(RuntimeError, match="clone failed"):
        ingest_repo(client, "https://github.com/a/b")


def test_ask_sample_questions_posts_each_question():
    asked = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        body = json.loads(request.content)
        asked.append(body["question"])
        return httpx.Response(
            200,
            json={"answer": "an answer", "citations": [], "confidence": "high", "retrieved_count": 1, "expanded_count": 0},
        )

    client = make_mock_client(handler)
    ask_sample_questions(client, "repo-1", ["Q1?", "Q2?"])

    assert asked == ["Q1?", "Q2?"]


def test_run_sample_review_posts_bundled_diff_and_prints_summary(capsys):
    received = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        received["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"findings": [{"file": "a.py"}], "summary": "1 finding", "risk_level": "low", "files_reviewed": 1},
        )

    client = make_mock_client(handler)
    run_sample_review(client, "repo-1")

    assert "diff" in received["body"]
    assert "eval(name)" in received["body"]["diff"]  # the bundled demo_review.diff
    assert "1 finding(s)" in capsys.readouterr().out


def test_ingest_repo_and_review_raise_http_status_error_on_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "unauthorized"})

    client = make_mock_client(handler)
    with pytest.raises(httpx.HTTPStatusError):
        ingest_repo(client, "https://github.com/a/b")


# -- read_dashboard_api_key_from_root_env -----------------------------------------------


def test_reads_dashboard_api_key_from_env_file(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=sk-abc\nDASHBOARD_API_KEY=local-dev-key\nOTHER=1\n")
    assert read_dashboard_api_key_from_root_env(env_file) == "local-dev-key"


def test_returns_none_when_env_file_missing(tmp_path):
    assert read_dashboard_api_key_from_root_env(tmp_path / "does-not-exist.env") is None


def test_returns_none_when_key_not_present_in_env_file(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=sk-abc\n")
    assert read_dashboard_api_key_from_root_env(env_file) is None


def test_returns_none_for_blank_value(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("DASHBOARD_API_KEY=\n")
    assert read_dashboard_api_key_from_root_env(env_file) is None


def test_strips_surrounding_quotes(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text('DASHBOARD_API_KEY="local-dev-key"\n')
    assert read_dashboard_api_key_from_root_env(env_file) == "local-dev-key"
