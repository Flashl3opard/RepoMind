import uuid
from dataclasses import dataclass
from typing import Literal, TypedDict

from pydantic import BaseModel, Field


class RewriteResult(BaseModel):
    rewritten_query: str = Field(
        ..., description="Code-search-friendly rewrite: likely identifiers, filenames, symbol names"
    )


class VerifyResult(BaseModel):
    grounded: bool = Field(..., description="True if every claim is supported by a cited chunk")
    unsupported_claims: list[str] = Field(
        default_factory=list, description="Claims in the answer not backed by any cited chunk"
    )


@dataclass(slots=True)
class LabeledChunk:
    """A chunk plus the stable [Cn] label it was shown to the LLM under."""

    label: str
    chunk_id: uuid.UUID
    file_path: str
    symbol_name: str
    start_line: int
    end_line: int
    source: str
    reason: str  # "retrieved" | "callee_of:<symbol>" | "caller_of:<symbol>"
    sources: list[str]  # retrieval provenance: "vector" / "keyword" / "graph"
    score: float


class LabeledChunkState(TypedDict):
    label: str
    chunk_id: str
    file_path: str
    symbol_name: str
    start_line: int
    end_line: int
    source: str
    reason: str
    sources: list[str]
    score: float


class Citation(TypedDict):
    label: str
    file_path: str
    start_line: int
    end_line: int
    symbol_name: str


class QAState(TypedDict):
    question: str
    rewritten_query: str
    retrieved: list[LabeledChunkState]
    expanded: list[LabeledChunkState]
    answer: str
    citations: list[Citation]
    grounded: bool
    attempts: int
    top_k: int


Confidence = Literal["high", "low"]
