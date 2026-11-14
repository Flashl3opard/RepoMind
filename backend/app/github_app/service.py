"""Orchestrates the webhook -> (ingest if needed) -> review -> post pipeline.

The pure decision functions (draft/fork/action filtering, default-branch push
detection) are kept separate from the DB/network plumbing so they're unit-testable
without a database. Idempotency is enforced by a unique constraint on ReviewRun
(repository_id, pr_number, head_sha); see get_or_create_review_run.
"""

import logging
import threading
import time
import uuid

from fastapi import BackgroundTasks
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agents.llm import build_chat_model
from app.config import Settings
from app.db.models import Repository, RepositoryStatus, ReviewRun, ReviewRunStatus
from app.db.session import SessionLocal
from app.github_app.auth import AppIdentityProvider, InstallationTokenProvider
from app.github_app.client import GitHubApiError, GitHubClient
from app.github_app.poster import post_review
from app.github_app.rate_limit import InstallationRateLimiter
from app.observability import log_review_run
from app.review.context_retrieval import estimate_tokens
from app.review.github import fetch_pr_diff
from app.review.graph import run_review
from app.services.embeddings import get_embeddings
from app.services.ingestion import ingest_repository

logger = logging.getLogger(__name__)

_HANDLED_PR_ACTIONS = {"opened", "synchronize", "reopened", "ready_for_review"}

# Serializes ingestion per repository within this process, so two webhook
# deliveries that both see a not-yet-ingested repo don't clone/parse/persist it
# concurrently. This is also how "if ingestion is in progress, retry once it
# finishes" is satisfied: the second caller simply blocks on the same lock.
_repo_locks: dict[uuid.UUID, threading.Lock] = {}
_repo_locks_guard = threading.Lock()

_token_provider: InstallationTokenProvider | None = None
_identity_provider: AppIdentityProvider | None = None
_rate_limiter: InstallationRateLimiter | None = None


def _get_repo_lock(repository_id: uuid.UUID) -> threading.Lock:
    with _repo_locks_guard:
        lock = _repo_locks.get(repository_id)
        if lock is None:
            lock = threading.Lock()
            _repo_locks[repository_id] = lock
        return lock


# -- pure webhook-payload decisions ----------------------------------------------------


def is_draft_pr(payload: dict) -> bool:
    return bool(payload.get("pull_request", {}).get("draft", False))


def is_fork_pr(payload: dict) -> bool:
    pr = payload.get("pull_request", {})
    head_repo = pr.get("head", {}).get("repo")
    base_repo = payload.get("repository", {})
    if head_repo is None:
        return True  # source repo of the fork was deleted; treat conservatively
    return head_repo.get("full_name") != base_repo.get("full_name")


def should_enqueue_review(payload: dict, allow_forks: bool) -> tuple[bool, str]:
    """(should_enqueue, reason_if_not)."""
    action = payload.get("action")
    if action not in _HANDLED_PR_ACTIONS:
        return False, f"unhandled action: {action}"
    if is_draft_pr(payload):
        return False, "draft PR"
    if is_fork_pr(payload) and not allow_forks:
        return False, "fork PR (GITHUB_REVIEW_FORKS is false)"
    return True, ""


def is_default_branch_push(payload: dict) -> bool:
    ref = payload.get("ref", "")
    default_branch = payload.get("repository", {}).get("default_branch")
    return bool(default_branch) and ref == f"refs/heads/{default_branch}"


# -- DB plumbing -------------------------------------------------------------------------


def get_or_create_repository(db: Session, clone_url: str, name: str) -> Repository:
    repository = db.scalars(select(Repository).where(Repository.url == clone_url)).first()
    if repository is not None:
        return repository
    repository = Repository(url=clone_url, name=name, status=RepositoryStatus.PENDING)
    db.add(repository)
    db.commit()
    db.refresh(repository)
    return repository


def get_or_create_review_run(
    db: Session, repository_id: uuid.UUID, pr_number: int, head_sha: str
) -> tuple[ReviewRun, bool]:
    """Returns (run, created). created=False means this exact (repo, PR, head_sha)
    delivery is a duplicate -- the caller must not enqueue work for it again."""

    def _find() -> ReviewRun | None:
        return db.scalars(
            select(ReviewRun).where(
                ReviewRun.repository_id == repository_id,
                ReviewRun.pr_number == pr_number,
                ReviewRun.head_sha == head_sha,
            )
        ).first()

    existing = _find()
    if existing is not None:
        return existing, False

    run = ReviewRun(
        repository_id=repository_id, pr_number=pr_number, head_sha=head_sha,
        status=ReviewRunStatus.QUEUED, finding_count=0,
    )
    db.add(run)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = _find()
        if existing is None:
            raise
        return existing, False
    db.refresh(run)
    return run, True


def _ensure_ingested(db: Session, repository: Repository, embeddings, *, access_token: str | None = None) -> None:
    if repository.status == RepositoryStatus.COMPLETED:
        return
    with _get_repo_lock(repository.id):
        db.refresh(repository)
        if repository.status == RepositoryStatus.COMPLETED:
            return
        ingest_repository(db, repository.id, embeddings=embeddings, access_token=access_token)
        db.refresh(repository)


def _resolve_clone_token(settings: Settings, installation_id: int | None) -> str | None:
    """The installation token also doubles as the clone credential for private repos
    (same token GitHub issues scoped to this installation's repos); falls back to a
    plain GITHUB_TOKEN PAT, or None for public clones."""
    if installation_id is not None and settings.GITHUB_APP_ID:
        return _get_token_provider(settings).get_token(installation_id)
    return settings.GITHUB_TOKEN


def _get_token_provider(settings: Settings) -> InstallationTokenProvider:
    global _token_provider
    if _token_provider is None:
        from app.github_app.auth import build_installation_token_provider

        _token_provider = build_installation_token_provider(settings)
    return _token_provider


def _get_identity_provider(settings: Settings) -> AppIdentityProvider:
    global _identity_provider
    if _identity_provider is None:
        from app.github_app.auth import build_app_identity_provider

        _identity_provider = build_app_identity_provider(settings)
    return _identity_provider


def _resolve_bot_login(settings: Settings, installation_id: int | None) -> str | None:
    """None (no dedup) when there's no GitHub App identity to resolve against, or if
    resolving it fails -- a failed lookup must not block posting the review itself."""
    if installation_id is None or not settings.GITHUB_APP_ID or not settings.GITHUB_APP_PRIVATE_KEY:
        return None
    try:
        return _get_identity_provider(settings).get_bot_login()
    except Exception:
        logger.warning("Could not resolve app bot login; comment dedup disabled for this run", exc_info=True)
        return None


def _get_rate_limiter(settings: Settings) -> InstallationRateLimiter:
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = InstallationRateLimiter(
            settings.GITHUB_RATE_LIMIT_CAPACITY, settings.GITHUB_RATE_LIMIT_REFILL_PER_MINUTE
        )
    return _rate_limiter


def process_pull_request_review(
    repository_id: uuid.UUID,
    review_run_id: uuid.UUID,
    full_name: str,
    pr_number: int,
    head_sha: str,
    installation_id: int | None,
    settings: Settings,
) -> None:
    """The background task: ingest-if-needed, review, post. Owns its own DB session
    since the request-scoped one from the webhook handler is already closed."""
    db = SessionLocal()
    try:
        run = db.get(ReviewRun, review_run_id)
        repository = db.get(Repository, repository_id)
        if run is None or repository is None:
            return
        run.status = ReviewRunStatus.RUNNING
        db.commit()

        token = _resolve_clone_token(settings, installation_id)
        embeddings = get_embeddings(settings)
        _ensure_ingested(db, repository, embeddings, access_token=token)
        db.refresh(repository)
        if repository.status != RepositoryStatus.COMPLETED:
            run.status = ReviewRunStatus.FAILED
            run.error = f"ingestion did not complete (status: {repository.status})"
            db.commit()
            return

        pr_url = f"https://github.com/{full_name}/pull/{pr_number}"
        diff_text = fetch_pr_diff(pr_url, token=token, timeout=settings.GITHUB_TIMEOUT_SECONDS)

        review_started_at = time.perf_counter()
        result = run_review(
            db,
            repository,
            diff_text,
            embeddings=embeddings,
            chat_model=build_chat_model(settings, timeout=settings.REVIEW_LLM_TIMEOUT_SECONDS),
            max_files=settings.REVIEW_MAX_FILES,
            max_diff_bytes=settings.REVIEW_MAX_DIFF_BYTES,
            max_diff_tokens=settings.REVIEW_MAX_DIFF_TOKENS,
            max_expanded_per_symbol=settings.REVIEW_MAX_EXPANDED_PER_SYMBOL,
            max_context_tokens=settings.REVIEW_MAX_CONTEXT_TOKENS,
            max_findings_per_file=settings.REVIEW_MAX_FINDINGS_PER_FILE,
            retrieval_top_k=settings.REVIEW_RETRIEVAL_TOP_K,
            context_mode=settings.REVIEW_CONTEXT_MODE,
        )
        log_review_run(
            repo=full_name,
            pr_number=pr_number,
            mode=settings.REVIEW_CONTEXT_MODE,
            latency_seconds=time.perf_counter() - review_started_at,
            finding_count=len(result.verified_findings),
            estimated_tokens=sum(estimate_tokens(c["source"]) for c in result.context),
            status="completed",
        )

        owner, repo_name = full_name.split("/", 1)
        if (
            not settings.REVIEW_DRY_RUN
            and installation_id is not None
            and not _get_rate_limiter(settings).allow(installation_id)
        ):
            run.status = ReviewRunStatus.FAILED
            run.error = "rate limited: too many reviews for this installation recently"
            db.commit()
            return

        bot_login = _resolve_bot_login(settings, installation_id)
        client = GitHubClient(token) if token else None
        try:
            if client is not None:
                post_review(
                    client, owner, repo_name, pr_number, head_sha, result, diff_text,
                    max_inline=settings.GITHUB_MAX_INLINE_COMMENTS, dry_run=settings.REVIEW_DRY_RUN,
                    bot_login=bot_login,
                )
            else:
                post_review(
                    None, owner, repo_name, pr_number, head_sha, result, diff_text,  # type: ignore[arg-type]
                    max_inline=settings.GITHUB_MAX_INLINE_COMMENTS, dry_run=True,
                    bot_login=bot_login,
                )
        except GitHubApiError as exc:
            if exc.status_code in (403, 429) and exc.retry_after_seconds and exc.retry_after_seconds <= 30:
                time.sleep(exc.retry_after_seconds)
                post_review(
                    client, owner, repo_name, pr_number, head_sha, result, diff_text,
                    max_inline=settings.GITHUB_MAX_INLINE_COMMENTS, dry_run=settings.REVIEW_DRY_RUN,
                    bot_login=bot_login,
                )
            else:
                raise

        run.status = ReviewRunStatus.DONE
        run.finding_count = len(result.verified_findings)
        run.findings = [dict(f) for f in result.verified_findings]
        run.summary = result.summary
        run.risk_level = result.risk_level
        db.commit()
    except Exception as exc:  # noqa: BLE001 - recorded on the ReviewRun row
        logger.exception("Review run %s failed", review_run_id)
        db.rollback()
        run = db.get(ReviewRun, review_run_id)
        if run is not None:
            run.status = ReviewRunStatus.FAILED
            run.error = str(exc)[:2000]
            db.commit()
    finally:
        db.close()


def handle_pull_request_webhook(payload: dict, background_tasks: BackgroundTasks, settings: Settings) -> dict:
    should_enqueue, reason = should_enqueue_review(payload, settings.GITHUB_REVIEW_FORKS)
    if not should_enqueue:
        return {"status": "skipped", "reason": reason}

    pr = payload["pull_request"]
    repo_payload = payload["repository"]
    installation_id = (payload.get("installation") or {}).get("id")
    pr_number = pr["number"]
    head_sha = pr["head"]["sha"]
    clone_url = repo_payload.get("clone_url") or repo_payload.get("html_url", "")
    full_name = repo_payload["full_name"]

    db = SessionLocal()
    try:
        repository = get_or_create_repository(db, clone_url, full_name)
        run, created = get_or_create_review_run(db, repository.id, pr_number, head_sha)
        repository_id = repository.id
        run_id = run.id
    finally:
        db.close()

    if not created:
        return {"status": "duplicate", "run_id": str(run_id)}

    background_tasks.add_task(
        process_pull_request_review, repository_id, run_id, full_name, pr_number, head_sha, installation_id, settings
    )
    return {"status": "queued", "run_id": str(run_id)}


def _run_reingestion_in_background(repository_id: uuid.UUID, installation_id: int | None, settings: Settings) -> None:
    db = SessionLocal()
    try:
        repository = db.get(Repository, repository_id)
        if repository is None:
            return
        token = _resolve_clone_token(settings, installation_id)
        with _get_repo_lock(repository_id):
            ingest_repository(db, repository_id, embeddings=get_embeddings(settings), access_token=token)
    except Exception:
        logger.exception("Re-ingestion failed for repository %s", repository_id)
    finally:
        db.close()


def handle_push_webhook(payload: dict, background_tasks: BackgroundTasks, settings: Settings) -> dict:
    if not is_default_branch_push(payload):
        return {"status": "ignored", "reason": "not a push to the default branch"}

    repo_payload = payload["repository"]
    clone_url = repo_payload.get("clone_url") or repo_payload.get("html_url", "")
    full_name = repo_payload["full_name"]
    installation_id = (payload.get("installation") or {}).get("id")

    db = SessionLocal()
    try:
        repository = get_or_create_repository(db, clone_url, full_name)
        repository_id = repository.id
    finally:
        db.close()

    background_tasks.add_task(_run_reingestion_in_background, repository_id, installation_id, settings)
    return {"status": "queued", "repository_id": str(repository_id)}
