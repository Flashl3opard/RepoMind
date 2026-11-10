import uuid

from pydantic import BaseModel, Field

from app.db.models import RepositoryStatus


class RepoCreateRequest(BaseModel):
    url: str = Field(..., min_length=1, description="Public git clone URL (https://, git://, ssh://)")


class RepoCreateResponse(BaseModel):
    id: uuid.UUID
    status: RepositoryStatus


class RepoStatusResponse(BaseModel):
    id: uuid.UUID
    url: str
    status: RepositoryStatus
    last_commit_sha: str | None
    error_message: str | None
    file_count: int
    chunk_count: int
