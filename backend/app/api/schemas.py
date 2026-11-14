import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

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


class ReviewRequest(BaseModel):
    pr_url: str | None = Field(None, description="https://github.com/owner/repo/pull/N")
    diff: str | None = Field(None, description="Raw unified diff text; no network needed")

    @model_validator(mode="after")
    def _exactly_one_of_pr_url_or_diff(self) -> "ReviewRequest":
        if (self.pr_url is None) == (self.diff is None):
            raise ValueError("Provide exactly one of 'pr_url' or 'diff'")
        return self


class FindingResponse(BaseModel):
    file: str
    start_line: int
    end_line: int
    severity: Literal["info", "warning", "error"]
    category: Literal["breaking_change", "bug_risk", "missing_test", "security", "style", "contract_change"]
    message: str
    evidence: list[str]
    caller_usage: str | None = None


class ReviewDebugInfo(BaseModel):
    skip_notes: list[str]
    dropped_count: int
    changed_symbols: list[dict[str, Any]]
    context: list[dict[str, Any]]


class ReviewResponse(BaseModel):
    findings: list[FindingResponse]
    summary: str
    risk_level: Literal["low", "medium", "high"]
    files_reviewed: int
    debug: ReviewDebugInfo | None = None
