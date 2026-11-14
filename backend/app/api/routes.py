import uuid
from urllib.parse import urlparse

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agents.llm import build_chat_model, build_verify_model
from app.agents.qa import run_qa
from app.api.schemas import (
    AskDebugInfo,
    AskRequest,
    AskResponse,
    CitationResponse,
    DebugChunkResponse,
    FindingResponse,
    RepoCreateRequest,
    RepoCreateResponse,
    RepoStatusResponse,
    ReviewDebugInfo,
    ReviewRequest,
    ReviewResponse,
)
from app.config import get_settings
from app.db.models import Chunk, File, Repository, RepositoryStatus, ReviewRun, ReviewRunStatus
from app.db.session import SessionLocal, get_db
from app.review.github import (
    GitHubError,
    GitHubRateLimitError,
    PullRequestNotFoundError,
    parse_pr_url,
)
from app.review.graph import ReviewInputError, ReviewTooLargeError, resolve_diff_text, run_review
from app.services.embeddings import get_embeddings
from app.services.ingestion import ingest_repository

router = APIRouter(prefix="/repos", tags=["repos"])

_ALLOWED_SCHEMES = {"http", "https", "git", "ssh"}


def _run_ingestion_in_background(repository_id: uuid.UUID) -> None:
    db = SessionLocal()
    try:
        ingest_repository(db, repository_id)
    except Exception:
        # Failure status/message is already recorded on the Repository row
        # by ingest_repository; nothing more to do with a bare BackgroundTasks setup.
        pass
    finally:
        db.close()


@router.post("", response_model=RepoCreateResponse, status_code=202)
def create_repository(
    payload: RepoCreateRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)
) -> RepoCreateResponse:
    parsed = urlparse(payload.url)
    if parsed.scheme not in _ALLOWED_SCHEMES or not parsed.netloc:
        raise HTTPException(status_code=422, detail="url must be a valid http(s)/git/ssh clone URL")

    name = parsed.path.rsplit("/", 1)[-1].removesuffix(".git") or payload.url
    repository = Repository(url=payload.url, name=name, status=RepositoryStatus.PENDING)
    db.add(repository)
    db.commit()
    db.refresh(repository)

    background_tasks.add_task(_run_ingestion_in_background, repository.id)

    return RepoCreateResponse(id=repository.id, status=repository.status)


@router.get("/{repository_id}", response_model=RepoStatusResponse)
def get_repository(repository_id: uuid.UUID, db: Session = Depends(get_db)) -> RepoStatusResponse:
    repository = db.get(Repository, repository_id)
    if repository is None:
        raise HTTPException(status_code=404, detail="repository not found")

    file_count = (
        db.scalar(select(func.count()).select_from(File).where(File.repository_id == repository.id)) or 0
    )
    chunk_count = (
        db.scalar(select(func.count()).select_from(Chunk).where(Chunk.repository_id == repository.id)) or 0
    )

    return RepoStatusResponse(
        id=repository.id,
        url=repository.url,
        status=repository.status,
        last_commit_sha=repository.last_commit_sha,
        error_message=repository.error_message,
        file_count=file_count,
        chunk_count=chunk_count,
    )


@router.post("/{repository_id}/ask", response_model=AskResponse)
def ask_repository(
    repository_id: uuid.UUID, payload: AskRequest, debug: bool = False, db: Session = Depends(get_db)
) -> AskResponse:
    repository = db.get(Repository, repository_id)
    if repository is None:
        raise HTTPException(status_code=404, detail="repository not found")
    if repository.status != RepositoryStatus.COMPLETED:
        raise HTTPException(
            status_code=409, detail=f"repository ingestion is not complete (status: {repository.status})"
        )

    settings = get_settings()
    result = run_qa(
        db,
        repository.id,
        payload.question,
        embeddings=get_embeddings(settings),
        chat_model=build_chat_model(settings),
        verify_model=build_verify_model(settings),
        top_k=settings.QA_DEFAULT_TOP_K,
        max_expanded=settings.QA_MAX_EXPANDED_CHUNKS,
        max_attempts=settings.QA_MAX_ATTEMPTS,
    )

    debug_info = None
    if debug:
        debug_info = AskDebugInfo(
            rewritten_query=result.rewritten_query,
            retrieved=[
                DebugChunkResponse(
                    label=c["label"],
                    file_path=c["file_path"],
                    symbol_name=c["symbol_name"],
                    reason=c["reason"],
                    sources=c["sources"],
                    score=c["score"],
                )
                for c in result.retrieved_debug
            ],
            expanded=[
                DebugChunkResponse(
                    label=c["label"],
                    file_path=c["file_path"],
                    symbol_name=c["symbol_name"],
                    reason=c["reason"],
                    sources=c["sources"],
                    score=c["score"],
                )
                for c in result.expanded_debug
            ],
            attempts=result.attempts,
        )

    return AskResponse(
        answer=result.answer,
        citations=[CitationResponse(**c) for c in result.citations],
        confidence=result.confidence,
        retrieved_count=result.retrieved_count,
        expanded_count=result.expanded_count,
        debug=debug_info,
    )


@router.post("/{repository_id}/review", response_model=ReviewResponse)
def review_repository(
    repository_id: uuid.UUID, payload: ReviewRequest, debug: bool = False, db: Session = Depends(get_db)
) -> ReviewResponse:
    """Review a PR against this repo's indexed base branch. Read-only: nothing from
    the PR is written to the database."""
    repository = db.get(Repository, repository_id)
    if repository is None:
        raise HTTPException(status_code=404, detail="repository not found")
    if repository.status != RepositoryStatus.COMPLETED:
        raise HTTPException(
            status_code=409, detail=f"repository ingestion is not complete (status: {repository.status})"
        )

    settings = get_settings()

    try:
        diff_text = resolve_diff_text(
            payload.diff, payload.pr_url, settings.GITHUB_TOKEN, settings.GITHUB_TIMEOUT_SECONDS
        )
    except ReviewInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except PullRequestNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except GitHubRateLimitError as exc:
        headers = {"Retry-After": str(int(exc.retry_after_seconds))} if exc.retry_after_seconds else None
        raise HTTPException(status_code=429, detail=str(exc), headers=headers) from exc
    except GitHubError as exc:
        raise HTTPException(status_code=502, detail=f"could not fetch PR diff: {exc}") from exc

    try:
        result = run_review(
            db,
            repository,
            diff_text,
            embeddings=get_embeddings(settings),
            chat_model=build_chat_model(settings, timeout=settings.REVIEW_LLM_TIMEOUT_SECONDS),
            max_files=settings.REVIEW_MAX_FILES,
            max_diff_bytes=settings.REVIEW_MAX_DIFF_BYTES,
            max_diff_tokens=settings.REVIEW_MAX_DIFF_TOKENS,
            max_expanded_per_symbol=settings.REVIEW_MAX_EXPANDED_PER_SYMBOL,
            max_context_tokens=settings.REVIEW_MAX_CONTEXT_TOKENS,
            max_findings_per_file=settings.REVIEW_MAX_FINDINGS_PER_FILE,
            retrieval_top_k=settings.REVIEW_RETRIEVAL_TOP_K,
        )
    except ReviewInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ReviewTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc

    # Record this manual run for the dashboard. Unlike webhook runs (deduped on
    # (repo, pr_number, head_sha) so a redelivered event is a no-op), a manual call
    # always creates a fresh row -- the caller explicitly asked for a review right
    # now, so a synthetic, always-unique head_sha avoids any dedup here.
    pr_number = 0
    if payload.pr_url is not None:
        try:
            _, _, pr_number = parse_pr_url(payload.pr_url)
        except ValueError:
            pr_number = 0
    review_run = ReviewRun(
        repository_id=repository.id,
        pr_number=pr_number,
        head_sha=f"manual-{uuid.uuid4().hex[:12]}",
        status=ReviewRunStatus.DONE,
        finding_count=len(result.verified_findings),
        source="manual",
        findings=[dict(f) for f in result.verified_findings],
        summary=result.summary,
        risk_level=result.risk_level,
    )
    db.add(review_run)
    db.commit()

    debug_info = None
    if debug and settings.REVIEW_DEBUG_ENABLED:
        debug_info = ReviewDebugInfo(
            skip_notes=result.skip_notes,
            dropped_count=result.dropped_count,
            changed_symbols=result.changed_symbols_debug,
            context=result.context_debug,
        )

    return ReviewResponse(
        findings=[FindingResponse(**f) for f in result.verified_findings],
        summary=result.summary,
        risk_level=result.risk_level,
        files_reviewed=result.files_reviewed,
        debug=debug_info,
    )
