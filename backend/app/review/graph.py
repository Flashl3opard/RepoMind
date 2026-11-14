"""Top-level LangGraph wiring for the PR reviewer:
parse_diff -> map_changes -> impact -> retrieve -> review -> verify -> summarize.

DB-backed; ties together every other app/review/ module the same way
app/agents/qa.py ties together app/retrieval/. The review is read-only on the index --
nothing from the PR is ever written to the database.
"""

import uuid
from dataclasses import dataclass
from typing import Any

from langchain_core.embeddings import Embeddings
from langgraph.graph import END, StateGraph
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Chunk, File, Repository
from app.parsing.registry import get_parser_for_path
from app.review.context_retrieval import (
    build_diff_only_context,
    build_naive_context,
    estimate_tokens,
    gather_review_context,
)
from app.review.diff_parser import old_side_ranges_by_file, parse_diff
from app.review.github import fetch_pr_diff
from app.review.impact import ImpactResult, analyze_impact
from app.review.map_changes import ChangedSymbol, IndexedChunkRef, map_file_changes
from app.review.prompts import build_review_prompt
from app.review.schemas import LLMReviewOutput, ReviewState, VerifiedFinding
from app.review.summarize import compute_risk_level, summarize_findings
from app.review.verify import verify_findings


class ReviewInputError(ValueError):
    """Malformed input (e.g. neither/both of diff and pr_url). Maps to HTTP 422."""


class ReviewTooLargeError(ValueError):
    """A configured cap (files / diff bytes / diff tokens) was exceeded. Maps to HTTP 413."""


def resolve_diff_text(
    diff: str | None, pr_url: str | None, github_token: str | None, github_timeout: float
) -> str:
    if diff is not None and pr_url is not None:
        raise ReviewInputError("Provide exactly one of 'diff' or 'pr_url', not both")
    if diff is not None:
        return diff
    if pr_url is not None:
        return fetch_pr_diff(pr_url, token=github_token, timeout=github_timeout)
    raise ReviewInputError("Provide one of 'diff' or 'pr_url'")


def _indexed_chunks_for_file(
    db: Session, repo_id: uuid.UUID, commit_sha: str | None, path: str
) -> list[IndexedChunkRef]:
    if commit_sha is None or not path:
        return []
    file_row = db.scalars(
        select(File).where(File.repository_id == repo_id, File.path == path, File.commit_sha == commit_sha)
    ).first()
    if file_row is None:
        return []
    chunks = db.scalars(select(Chunk).where(Chunk.file_id == file_row.id)).all()
    return [
        IndexedChunkRef(
            chunk_id=c.id, symbol_name=c.symbol_name, kind=c.kind, start_line=c.start_line,
            end_line=c.end_line, source=c.source,
        )
        for c in chunks
    ]


def build_review_graph(
    *,
    db: Session,
    repo_id: uuid.UUID,
    base_commit_sha: str | None,
    embeddings: Embeddings,
    chat_model: Any,
    max_files: int,
    max_expanded_per_symbol: int,
    max_context_tokens: int,
    max_findings_per_file: int,
    retrieval_top_k: int,
    context_mode: str = "full",
    full_file_contents: dict[str, str] | None = None,
) -> Any:
    def parse_diff_node(state: ReviewState) -> dict:
        file_diffs = parse_diff(state["diff_text"])
        if len(file_diffs) > max_files:
            raise ReviewTooLargeError(f"PR touches {len(file_diffs)} files, over the cap of {max_files}")
        skip_notes = [f"skipped binary file {fd.path}" for fd in file_diffs if fd.is_binary]
        return {"file_diffs": file_diffs, "skip_notes": skip_notes}

    def map_changes_node(state: ReviewState) -> dict:
        changed_symbols: list[ChangedSymbol] = []
        for file_diff in state["file_diffs"]:
            parser = get_parser_for_path(file_diff.lookup_path or file_diff.path)
            indexed = _indexed_chunks_for_file(db, repo_id, base_commit_sha, file_diff.lookup_path)
            changed_symbols.extend(map_file_changes(file_diff, parser, indexed))
        return {"changed_symbols": changed_symbols}

    def impact_node(state: ReviewState) -> dict:
        if context_mode in ("diff_only", "naive"):
            return {"impacts": []}
        old_ranges = old_side_ranges_by_file(state["file_diffs"])
        impacts: list[ImpactResult] = []
        for symbol in state["changed_symbols"]:
            result = analyze_impact(db, repo_id, symbol, old_ranges, max_extra=max_expanded_per_symbol)
            if result is not None:
                impacts.append(result)
        return {"impacts": impacts}

    def retrieve_node(state: ReviewState) -> dict:
        if context_mode == "diff_only":
            return {"context": build_diff_only_context(state["changed_symbols"])}
        if context_mode == "naive":
            return {"context": build_naive_context(state["file_diffs"], full_file_contents)}
        context = gather_review_context(
            db,
            repo_id,
            state["changed_symbols"],
            state["impacts"],
            embeddings,
            top_k=retrieval_top_k,
            max_tokens=max_context_tokens,
        )
        return {"context": context}

    def review_node(state: ReviewState) -> dict:
        if not state["changed_symbols"]:
            return {"raw_findings": []}
        prompt = build_review_prompt(state["file_diffs"], state["changed_symbols"], state["context"])
        result = chat_model.with_structured_output(LLMReviewOutput).invoke(prompt)
        return {"raw_findings": result.findings}

    def verify_node(state: ReviewState) -> dict:
        verified, dropped = verify_findings(
            state["raw_findings"],
            state["context"],
            state["changed_symbols"],
            state["file_diffs"],
            max_per_file=max_findings_per_file,
            strict_gates=context_mode != "naive",
        )
        return {"verified_findings": verified, "dropped_count": dropped}

    def summarize_node(state: ReviewState) -> dict:
        return {
            "summary": summarize_findings(state["verified_findings"]),
            "risk_level": compute_risk_level(state["verified_findings"]),
        }

    graph = StateGraph(ReviewState)
    graph.add_node("parse_diff", parse_diff_node)
    graph.add_node("map_changes", map_changes_node)
    graph.add_node("impact", impact_node)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("review", review_node)
    graph.add_node("verify", verify_node)
    graph.add_node("summarize", summarize_node)

    graph.set_entry_point("parse_diff")
    graph.add_edge("parse_diff", "map_changes")
    graph.add_edge("map_changes", "impact")
    graph.add_edge("impact", "retrieve")
    graph.add_edge("retrieve", "review")
    graph.add_edge("review", "verify")
    graph.add_edge("verify", "summarize")
    graph.add_edge("summarize", END)

    return graph.compile()


@dataclass(slots=True)
class ReviewResult:
    verified_findings: list[VerifiedFinding]
    summary: str
    risk_level: str
    dropped_count: int
    skip_notes: list[str]
    files_reviewed: int
    changed_symbols_debug: list[dict]
    context_debug: list[dict]
    context: list[dict]  # full labeled context (incl. start/end line), for poster.py evidence formatting


def run_review(
    db: Session,
    repository: Repository,
    diff_text: str,
    *,
    embeddings: Embeddings,
    chat_model: Any,
    max_files: int = 30,
    max_diff_bytes: int = 300_000,
    max_diff_tokens: int = 20_000,
    max_expanded_per_symbol: int = 6,
    max_context_tokens: int = 6_000,
    max_findings_per_file: int = 5,
    retrieval_top_k: int = 6,
    context_mode: str = "full",
    full_file_contents: dict[str, str] | None = None,
) -> ReviewResult:
    diff_bytes = len(diff_text.encode("utf-8"))
    if diff_bytes > max_diff_bytes:
        raise ReviewTooLargeError(f"diff is {diff_bytes} bytes, over the cap of {max_diff_bytes}")
    diff_tokens = estimate_tokens(diff_text)
    if diff_tokens > max_diff_tokens:
        raise ReviewTooLargeError(f"diff is too large to review (~{diff_tokens} estimated tokens)")

    graph = build_review_graph(
        db=db,
        repo_id=repository.id,
        base_commit_sha=repository.last_commit_sha,
        embeddings=embeddings,
        chat_model=chat_model,
        max_files=max_files,
        max_expanded_per_symbol=max_expanded_per_symbol,
        max_context_tokens=max_context_tokens,
        max_findings_per_file=max_findings_per_file,
        retrieval_top_k=retrieval_top_k,
        context_mode=context_mode,
        full_file_contents=full_file_contents,
    )
    initial_state: ReviewState = {
        "diff_text": diff_text,
        "repo_id": str(repository.id),
        "file_diffs": [],
        "skip_notes": [],
        "changed_symbols": [],
        "impacts": [],
        "context": [],
        "raw_findings": [],
        "verified_findings": [],
        "dropped_count": 0,
        "summary": "",
        "risk_level": "low",
    }
    final_state: ReviewState = graph.invoke(initial_state)

    return ReviewResult(
        verified_findings=final_state["verified_findings"],
        summary=final_state["summary"],
        risk_level=final_state["risk_level"],
        dropped_count=final_state["dropped_count"],
        skip_notes=final_state["skip_notes"],
        files_reviewed=len(final_state["file_diffs"]),
        changed_symbols_debug=[
            {
                "file": s.file_path,
                "symbol": s.symbol_name,
                "change_type": s.change_type,
                "signature_changed": s.signature_changed,
                "details": s.signature_change_details,
            }
            for s in final_state["changed_symbols"]
        ],
        context_debug=[
            {"label": c["label"], "file_path": c["file_path"], "reason": c["reason"], "sources": c["sources"]}
            for c in final_state["context"]
        ],
        context=[dict(c) for c in final_state["context"]],
    )
