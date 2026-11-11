import uuid
from typing import Literal

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


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1)


class CitationResponse(BaseModel):
    label: str
    file_path: str
    start_line: int
    end_line: int
    symbol_name: str


class DebugChunkResponse(BaseModel):
    label: str
    file_path: str
    symbol_name: str
    reason: str
    sources: list[str]
    score: float


class AskDebugInfo(BaseModel):
    rewritten_query: str
    retrieved: list[DebugChunkResponse]
    expanded: list[DebugChunkResponse]
    attempts: int


class AskResponse(BaseModel):
    answer: str
    citations: list[CitationResponse]
    confidence: Literal["high", "low"]
    retrieved_count: int
    expanded_count: int
    debug: AskDebugInfo | None = None
