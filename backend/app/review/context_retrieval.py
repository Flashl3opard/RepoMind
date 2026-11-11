"""Builds retrieval queries from changed symbols (+ their docstrings), runs hybrid
search, and merges with impact-analysis evidence into one bounded, labeled context for
the review LLM. Reuses `hybrid_search` and the existing `LabeledChunkState` shape so
citation handling (app/agents/citations.py) works unchanged.
"""

import uuid

from langchain_core.embeddings import Embeddings
from sqlalchemy.orm import Session

from app.agents.schemas import LabeledChunkState
from app.db.models import Chunk
from app.retrieval.hybrid import hybrid_search, merge_retrieved
from app.review.impact import ImpactResult
from app.review.map_changes import ChangedSymbol
from app.review.signature import extract_docstring

_CHARS_PER_TOKEN = 4  # cheap heuristic; avoids adding a real tokenizer dependency


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // _CHARS_PER_TOKEN)


def build_symbol_query(symbol: ChangedSymbol) -> str:
    docstring = extract_docstring(symbol.new_source, symbol.language) if symbol.new_source else None
    return f"{symbol.symbol_name} {docstring}" if docstring else symbol.symbol_name


def _to_labeled(chunk: Chunk, label: str, reason: str, sources: list[str], score: float) -> LabeledChunkState:
    return LabeledChunkState(
        label=label,
        chunk_id=str(chunk.id),
        file_path=chunk.file.path,
        symbol_name=chunk.symbol_name,
        start_line=chunk.start_line,
        end_line=chunk.end_line,
        source=chunk.source,
        reason=reason,
        sources=sources,
        score=score,
    )


def gather_review_context(
    db: Session,
    repo_id: uuid.UUID,
    changed_symbols: list[ChangedSymbol],
    impacts: list[ImpactResult],
    embeddings: Embeddings,
    top_k: int = 8,
    max_tokens: int = 6000,
) -> list[LabeledChunkState]:
    """Impact evidence (callers/callees/referencing tests) is added first -- it's what
    the breaking_change verify rule needs -- then hybrid-retrieved chunks fill the rest
    of the token budget. Always includes at least one chunk (if any exist) even if it
    alone exceeds `max_tokens`, so the context is never empty by a hair's margin."""
    labeled: list[LabeledChunkState] = []
    seen_chunk_ids: set[str] = set()
    used_tokens = 0
    next_label = 1

    def try_add(chunk: Chunk, reason: str, sources: list[str], score: float) -> None:
        nonlocal used_tokens, next_label
        chunk_id = str(chunk.id)
        if chunk_id in seen_chunk_ids:
            return
        cost = estimate_tokens(chunk.source)
        if labeled and used_tokens + cost > max_tokens:
            return
        seen_chunk_ids.add(chunk_id)
        labeled.append(_to_labeled(chunk, f"C{next_label}", reason, sources, score))
        next_label += 1
        used_tokens += cost

    for impact in impacts:
        symbol_tag = impact.symbol.symbol_name
        for callee in impact.callees:
            try_add(callee, f"callee_of:{symbol_tag}", ["graph"], 1.0)
        for caller in impact.callers:
            tag = f"caller_of:{symbol_tag}" if caller.touched_by_pr else f"stale_caller_of:{symbol_tag}"
            try_add(caller.chunk, tag, ["graph"], 1.0)
        for test_chunk in impact.referencing_tests:
            try_add(test_chunk, f"test_for:{symbol_tag}", ["graph"], 1.0)

    retrieved_sets = [
        hybrid_search(db, repo_id, build_symbol_query(symbol), embeddings, top_k=top_k)
        for symbol in changed_symbols
    ]
    merged = merge_retrieved(retrieved_sets, top_k=top_k * max(1, len(changed_symbols))) if retrieved_sets else []

    for retrieved in merged:
        try_add(retrieved.chunk, "retrieved", list(retrieved.sources), retrieved.score)

    return labeled
