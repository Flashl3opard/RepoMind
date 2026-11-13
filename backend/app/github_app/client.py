"""Thin GitHub REST client for posting reviews, authenticated with an installation
token. Separate from app/review/github.py (anonymous/PAT diff fetches only) since
this one needs write access and a different auth scheme. Never logs the token.
"""

import httpx


class GitHubApiError(RuntimeError):
    def __init__(self, message: str, status_code: int, response_text: str = "", retry_after_seconds: float | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_text = response_text
        self.retry_after_seconds = retry_after_seconds


def _retry_after(response: httpx.Response) -> float | None:
    retry_after = response.headers.get("retry-after")
    if retry_after is None:
        return None
    try:
        return float(retry_after)
    except ValueError:
        return None


def _raise_for_status(response: httpx.Response) -> None:
    if response.status_code < 400:
        return
    raise GitHubApiError(
        f"GitHub API error {response.status_code}",
        response.status_code,
        response.text[:500],
        retry_after_seconds=_retry_after(response),
    )


class GitHubClient:
    def __init__(self, token: str, timeout: float = 15.0) -> None:
        self._token = token
        self._timeout = timeout

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def list_review_comments(self, owner: str, repo: str, pr_number: int) -> list[dict]:
        comments: list[dict] = []
        url: str | None = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/comments"
        params: dict | None = {"per_page": 100}
        while url:
            response = httpx.get(url, headers=self._headers(), params=params, timeout=self._timeout)
            _raise_for_status(response)
            comments.extend(response.json())
            url = response.links.get("next", {}).get("url")
            params = None
        return comments

    def create_review(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        commit_id: str,
        body: str,
        comments: list[dict],
        event: str = "COMMENT",
    ) -> dict:
        url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/reviews"
        payload = {"commit_id": commit_id, "body": body, "event": event, "comments": comments}
        response = httpx.post(url, headers=self._headers(), json=payload, timeout=self._timeout)
        _raise_for_status(response)
        return response.json()
