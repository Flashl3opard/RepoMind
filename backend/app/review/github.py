"""Minimal GitHub PR diff fetcher.

A single API call, using content negotiation to get the diff media type directly from
the PR endpoint -- no per-file content fetches are needed, since map_changes.py only
ever needs each hunk's own new-side text (see its docstring for why that's enough).
Never logs headers or the token.
"""

import re

import httpx

_PR_URL_RE = re.compile(r"^https?://github\.com/([^/]+)/([^/]+)/pull/(\d+)/?$")


class GitHubError(RuntimeError):
    pass


class PullRequestNotFoundError(GitHubError):
    pass


class GitHubRateLimitError(GitHubError):
    def __init__(self, message: str, retry_after_seconds: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


def parse_pr_url(pr_url: str) -> tuple[str, str, int]:
    match = _PR_URL_RE.match(pr_url.strip())
    if match is None:
        raise ValueError(f"Not a GitHub PR URL: {pr_url!r}")
    owner, repo, number = match.groups()
    return owner, repo, int(number)


def fetch_pr_diff(pr_url: str, token: str | None = None, timeout: float = 15.0) -> str:
    """Fetch a PR's full unified diff. Raises PullRequestNotFoundError on a 404,
    GitHubRateLimitError when the API says the rate limit is exhausted, or GitHubError
    for any other failure (including a timeout)."""
    owner, repo, number = parse_pr_url(pr_url)
    headers = {"Accept": "application/vnd.github.v3.diff"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{number}"
    try:
        response = httpx.get(url, headers=headers, timeout=timeout, follow_redirects=True)
    except httpx.TimeoutException as exc:
        raise GitHubError(f"GitHub request timed out after {timeout}s") from exc
    except httpx.HTTPError as exc:
        raise GitHubError(f"GitHub request failed: {exc}") from exc

    if response.status_code == 404:
        raise PullRequestNotFoundError(f"Pull request not found: {pr_url}")

    if response.status_code in (403, 429):
        remaining = response.headers.get("x-ratelimit-remaining")
        reset = response.headers.get("x-ratelimit-reset")
        retry_after = response.headers.get("retry-after")
        retry_seconds: float | None = None
        if retry_after is not None:
            try:
                retry_seconds = float(retry_after)
            except ValueError:
                retry_seconds = None
        if response.status_code == 429 or remaining == "0":
            raise GitHubRateLimitError(
                f"GitHub rate limit exceeded (resets at {reset or 'unknown'})",
                retry_after_seconds=retry_seconds,
            )
        raise GitHubError(f"GitHub request forbidden ({response.status_code}): {response.text[:200]}")

    if response.status_code >= 400:
        raise GitHubError(f"GitHub request failed ({response.status_code}): {response.text[:200]}")

    return response.text
