import uuid
from urllib.parse import urlparse

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.schemas import RepoCreateRequest, RepoCreateResponse, RepoStatusResponse
from app.db.models import Chunk, File, Repository, RepositoryStatus
from app.db.session import SessionLocal, get_db
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
