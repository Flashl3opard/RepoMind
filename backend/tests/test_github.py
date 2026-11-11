import httpx
import pytest

import app.review.github as github_module
from app.review.github import (
    GitHubError,
    GitHubRateLimitError,
    PullRequestNotFoundError,
    fetch_pr_diff,
    parse_pr_url,
)


def test_parse_pr_url():
    assert parse_pr_url("https://github.com/owner/repo/pull/42") == ("owner", "repo", 42)


def test_parse_pr_url_with_trailing_slash():
    assert parse_pr_url("https://github.com/owner/repo/pull/42/") == ("owner", "repo", 42)


def test_parse_pr_url_rejects_non_github_url():
    with pytest.raises(ValueError):
        parse_pr_url("https://gitlab.com/owner/repo/pull/42")


def _fake_response(status_code: int, text: str = "", headers: dict | None = None) -> httpx.Response:
    return httpx.Response(status_code=status_code, text=text, headers=headers or {})


def test_fetch_pr_diff_success(monkeypatch):
    def fake_get(url, headers, timeout, follow_redirects):
        assert "Accept" in headers and headers["Accept"] == "application/vnd.github.v3.diff"
        return _fake_response(200, text="diff --git a/x b/x\n")

    monkeypatch.setattr(github_module.httpx, "get", fake_get)
    diff = fetch_pr_diff("https://github.com/owner/repo/pull/1")
    assert diff.startswith("diff --git")


def test_fetch_pr_diff_never_sends_token_in_url_and_includes_auth_header(monkeypatch):
    captured = {}

    def fake_get(url, headers, timeout, follow_redirects):
        captured["url"] = url
        captured["headers"] = headers
        return _fake_response(200, text="diff")

    monkeypatch.setattr(github_module.httpx, "get", fake_get)
    fetch_pr_diff("https://github.com/owner/repo/pull/1", token="secret-token")
    assert "secret-token" not in captured["url"]
    assert captured["headers"]["Authorization"] == "Bearer secret-token"


def test_fetch_pr_diff_404_raises_not_found(monkeypatch):
    monkeypatch.setattr(github_module.httpx, "get", lambda *a, **k: _fake_response(404))
    with pytest.raises(PullRequestNotFoundError):
        fetch_pr_diff("https://github.com/owner/repo/pull/999")


def test_fetch_pr_diff_rate_limit_403_raises_rate_limit_error(monkeypatch):
    def fake_get(*a, **k):
        return _fake_response(403, headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "12345"})

    monkeypatch.setattr(github_module.httpx, "get", fake_get)
    with pytest.raises(GitHubRateLimitError):
        fetch_pr_diff("https://github.com/owner/repo/pull/1")


def test_fetch_pr_diff_429_raises_rate_limit_error_with_retry_after(monkeypatch):
    def fake_get(*a, **k):
        return _fake_response(429, headers={"retry-after": "30"})

    monkeypatch.setattr(github_module.httpx, "get", fake_get)
    with pytest.raises(GitHubRateLimitError) as exc_info:
        fetch_pr_diff("https://github.com/owner/repo/pull/1")
    assert exc_info.value.retry_after_seconds == 30.0


def test_fetch_pr_diff_403_without_rate_limit_marker_raises_generic_error(monkeypatch):
    monkeypatch.setattr(github_module.httpx, "get", lambda *a, **k: _fake_response(403, text="forbidden"))
    with pytest.raises(GitHubError):
        fetch_pr_diff("https://github.com/owner/repo/pull/1")


def test_fetch_pr_diff_timeout_raises_github_error(monkeypatch):
    def fake_get(*a, **k):
        raise httpx.TimeoutException("timed out")

    monkeypatch.setattr(github_module.httpx, "get", fake_get)
    with pytest.raises(GitHubError):
        fetch_pr_diff("https://github.com/owner/repo/pull/1")


def test_fetch_pr_diff_server_error_raises_github_error(monkeypatch):
    monkeypatch.setattr(github_module.httpx, "get", lambda *a, **k: _fake_response(500, text="boom"))
    with pytest.raises(GitHubError):
        fetch_pr_diff("https://github.com/owner/repo/pull/1")
