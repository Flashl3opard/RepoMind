"""Seeds a running RepoMind stack with demo content: ingests a small public Python
repo, asks it 3 sample questions, and runs one PR review against a bundled sample
diff -- so the dashboard (frontend/) has something to show right after
`docker compose up --build`.

Talks to the real backend over HTTP (--backend-url, default http://localhost:8000);
this is a demo client exercising the real API, not a script that reaches into the
database directly. The review step uses POST /repos/{id}/review with a raw diff
(demo_review.diff, bundled next to this script), which never calls the GitHub API --
only the GitHub App webhook path (app/github_app/service.py) ever posts a review, and
even that only when REVIEW_DRY_RUN=false. This script is safe to run regardless of
that setting.

The dashboard API key defaults to $DASHBOARD_API_KEY, falling back to DASHBOARD_API_KEY
in the root .env file (the one `docker compose up` reads) if that env var isn't set in
the current shell -- so running this right after `docker compose up --build`, from a
shell that never exported it, still works without extra steps. --api-key overrides both.

Usage:
    uv run python scripts/seed_demo.py
    uv run python scripts/seed_demo.py --repo-url https://github.com/pallets/click
    uv run python scripts/seed_demo.py --backend-url http://localhost:8000 --api-key ...
"""

import argparse
import os
import re
import sys
import time
from pathlib import Path

import httpx

ROOT_ENV_PATH = Path(__file__).parent.parent.parent / ".env"
DEFAULT_REPO_URL = "https://github.com/pallets/flask"
DEFAULT_QUESTIONS = [
    "What does this project do?",
    "How is configuration handled?",
    "Where are the main entry points defined?",
]
SAMPLE_DIFF_PATH = Path(__file__).parent / "demo_review.diff"
POLL_INTERVAL_SECONDS = 4
POLL_TIMEOUT_SECONDS = 600
TERMINAL_STATUSES = {"completed", "failed"}


def read_dashboard_api_key_from_root_env(env_path: Path = ROOT_ENV_PATH) -> str | None:
    """Best-effort fallback: a plain `KEY=value` line scan, not a real .env parser --
    good enough for the one variable this script needs when $DASHBOARD_API_KEY isn't
    already exported. Returns None if the file or the key isn't present."""
    if not env_path.is_file():
        return None
    match = re.search(r"^DASHBOARD_API_KEY=(.*)$", env_path.read_text(encoding="utf-8"), re.MULTILINE)
    if match is None:
        return None
    value = match.group(1).strip().strip("'\"")
    return value or None


def make_client(backend_url: str, api_key: str | None) -> httpx.Client:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    return httpx.Client(base_url=backend_url, headers=headers, timeout=60.0)


def ingest_repo(client: httpx.Client, repo_url: str) -> str:
    response = client.post("/repos", json={"url": repo_url})
    response.raise_for_status()
    repo_id = response.json()["id"]
    print(f"ingesting {repo_url} -> repository {repo_id}")

    deadline = time.monotonic() + POLL_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        status_response = client.get(f"/repos/{repo_id}")
        status_response.raise_for_status()
        body = status_response.json()
        print(f"  status={body['status']} files={body['file_count']} chunks={body['chunk_count']}")
        if body["status"] in TERMINAL_STATUSES:
            if body["status"] == "failed":
                raise RuntimeError(f"ingestion failed: {body.get('error_message')}")
            return repo_id
        time.sleep(POLL_INTERVAL_SECONDS)
    raise TimeoutError(f"ingestion of {repo_url} did not complete within {POLL_TIMEOUT_SECONDS}s")


def ask_sample_questions(client: httpx.Client, repo_id: str, questions: list[str]) -> None:
    for question in questions:
        response = client.post(f"/repos/{repo_id}/ask", json={"question": question})
        response.raise_for_status()
        body = response.json()
        print(f"\nQ: {question}")
        print(f"A ({body['confidence']} confidence): {body['answer'][:300]}")


def run_sample_review(client: httpx.Client, repo_id: str) -> None:
    diff_text = SAMPLE_DIFF_PATH.read_text()
    response = client.post(f"/repos/{repo_id}/review", json={"diff": diff_text})
    response.raise_for_status()
    body = response.json()
    print(f"\nreview: {len(body['findings'])} finding(s), risk={body['risk_level']}")
    print(f"summary: {body['summary']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--backend-url", default="http://localhost:8000")
    parser.add_argument("--api-key", default=None, help="defaults to $DASHBOARD_API_KEY")
    parser.add_argument("--repo-url", default=DEFAULT_REPO_URL, help=f"default: {DEFAULT_REPO_URL}")
    args = parser.parse_args()

    api_key = args.api_key or os.environ.get("DASHBOARD_API_KEY") or read_dashboard_api_key_from_root_env()

    try:
        with make_client(args.backend_url, api_key) as client:
            repo_id = ingest_repo(client, args.repo_url)
            ask_sample_questions(client, repo_id, DEFAULT_QUESTIONS)
            run_sample_review(client, repo_id)
    except httpx.HTTPStatusError as exc:
        print(f"request to {exc.request.url} failed: {exc.response.status_code} {exc.response.text[:300]}", file=sys.stderr)
        return 1
    except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
        print(f"could not reach the backend at {args.backend_url}: {exc}", file=sys.stderr)
        return 1

    print("\ndone -- open the dashboard to see the seeded repo, Q&A, and review.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
