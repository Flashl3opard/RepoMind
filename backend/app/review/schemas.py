"""Pydantic I/O schemas and LangGraph state for the PR reviewer."""

from typing import Literal, TypedDict

from pydantic import BaseModel, Field

from app.agents.schemas import LabeledChunkState
from app.review.diff_parser import FileDiff
from app.review.impact import ImpactResult
from app.review.map_changes import ChangedSymbol

Severity = Literal["info", "warning", "error"]
Category = Literal["breaking_change", "bug_risk", "missing_test", "security", "style", "contract_change"]
RiskLevel = Literal["low", "medium", "high"]


class LLMFinding(BaseModel):
    """One finding as the LLM proposes it -- subject to deterministic verification in
    verify.py before it's ever returned to the caller."""

    file: str
    start_line: int
    end_line: int
    severity: Severity
    category: Category
    message: str
    evidence: list[str] = Field(default_factory=list, description="[Cn] labels supporting this finding")
    # Required (and checked) only for category == "contract_change": a short verbatim
    # quote from the cited caller chunk showing how it actually uses the changed
    # symbol. See verify.passes_contract_change_gate.
    caller_usage: str | None = Field(
        default=None, description="Verbatim quote from a cited caller chunk, required for category='contract_change'"
    )


class LLMReviewOutput(BaseModel):
    findings: list[LLMFinding] = Field(default_factory=list)


class VerifiedFinding(TypedDict):
    file: str
    start_line: int
    end_line: int
    severity: Severity
    category: Category
    message: str
    evidence: list[str]
    caller_usage: str | None


class ReviewState(TypedDict):
    # inputs
    diff_text: str
    repo_id: str
    # parse_diff
    file_diffs: list[FileDiff]
    skip_notes: list[str]  # e.g. "skipped binary file image.png"
    # map_changes
    changed_symbols: list[ChangedSymbol]
    # impact
    impacts: list[ImpactResult]
    # retrieve
    context: list[LabeledChunkState]
    # review
    raw_findings: list[LLMFinding]
    # verify
    verified_findings: list[VerifiedFinding]
    dropped_count: int
    # summarize
    summary: str
    risk_level: RiskLevel
