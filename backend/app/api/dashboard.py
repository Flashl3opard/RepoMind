"""Read-only dashboard endpoints: repo list, review history, review detail, and the
latest benchmark results. New file; the existing routes in app/api/routes.py are left
untouched. Auth is applied globally (see app/api/dashboard_auth.py), not here.
"""

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.schemas import FindingResponse
from app.db.models import Chunk, File, Repository, RepositoryStatus, ReviewRun, ReviewRunStatus
from app.db.session import get_db

router = APIRouter(tags=["dashboard"])

BENCH_RESULTS_DIR = Path(__file__).resolve().parents[2] / "evals" / "bench" / "results"


class RepoListItem(BaseModel):
    id: uuid.UUID
    url: str
    full_name: str
    status: RepositoryStatus
    commit_sha: str | None
    file_count: int
    chunk_count: int
    last_ingested_at: datetime


class ReviewRunListItem(BaseModel):
    id: uuid.UUID
    pr_number: int
    head_sha: str
    status: ReviewRunStatus
    finding_count: int
    risk_level: str | None
    source: str
    created_at: datetime


class ReviewRunDetail(BaseModel):
    id: uuid.UUID
    repository_id: uuid.UUID
    pr_number: int
    head_sha: str
    status: ReviewRunStatus
    finding_count: int
    findings: list[FindingResponse] | None
    summary: str | None
    risk_level: str | None
    error: str | None
    source: str
    created_at: datetime
    updated_at: datetime


@router.get("/repos", response_model=list[RepoListItem])
def list_repos(db: Session = Depends(get_db)) -> list[RepoListItem]:
    repositories = db.scalars(select(Repository).order_by(Repository.updated_at.desc())).all()

    items: list[RepoListItem] = []
    for repository in repositories:
        file_count = (
            db.scalar(select(func.count()).select_from(File).where(File.repository_id == repository.id)) or 0
        )
        chunk_count = (
            db.scalar(select(func.count()).select_from(Chunk).where(Chunk.repository_id == repository.id)) or 0
        )
        items.append(
            RepoListItem(
                id=repository.id,
                url=repository.url,
                full_name=repository.name,
                status=repository.status,
                commit_sha=repository.last_commit_sha,
                file_count=file_count,
                chunk_count=chunk_count,
                last_ingested_at=repository.updated_at,
            )
        )
    return items


@router.get("/repos/{repository_id}/reviews", response_model=list[ReviewRunListItem])
def list_repo_reviews(repository_id: uuid.UUID, db: Session = Depends(get_db)) -> list[ReviewRunListItem]:
    repository = db.get(Repository, repository_id)
    if repository is None:
        raise HTTPException(status_code=404, detail="repository not found")

    runs = db.scalars(
        select(ReviewRun).where(ReviewRun.repository_id == repository_id).order_by(ReviewRun.created_at.desc())
    ).all()
    return [
        ReviewRunListItem(
            id=run.id, pr_number=run.pr_number, head_sha=run.head_sha, status=run.status,
            finding_count=run.finding_count, risk_level=run.risk_level, source=run.source,
            created_at=run.created_at,
        )
        for run in runs
    ]


@router.get("/reviews/{run_id}", response_model=ReviewRunDetail)
def get_review_run(run_id: uuid.UUID, db: Session = Depends(get_db)) -> ReviewRunDetail:
    run = db.get(ReviewRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="review run not found")

    return ReviewRunDetail(
        id=run.id, repository_id=run.repository_id, pr_number=run.pr_number, head_sha=run.head_sha,
        status=run.status, finding_count=run.finding_count, findings=run.findings, summary=run.summary,
        risk_level=run.risk_level, error=run.error, source=run.source, created_at=run.created_at,
        updated_at=run.updated_at,
    )


def _latest_benchmark_results_path() -> Path | None:
    if not BENCH_RESULTS_DIR.is_dir():
        return None
    json_files = sorted(BENCH_RESULTS_DIR.glob("*.json"))
    return json_files[-1] if json_files else None


@router.get("/benchmark/latest")
def get_latest_benchmark_results() -> dict[str, Any]:
    path = _latest_benchmark_results_path()
    if path is None:
        raise HTTPException(status_code=404, detail="no benchmark results found; run evals/bench/run.py first")
    data = json.loads(path.read_text(encoding="utf-8"))
    data["generated_at"] = path.stem
    return data
