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
    RepoCreateRequest,
    RepoCreateResponse,
    RepoStatusResponse,
)
from app.config import get_settings
from app.db.models import Chunk, File, Repository, RepositoryStatus
from app.db.session import SessionLocal, get_db
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
