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
from app.review.diff_parser import FileDiff
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


def build_diff_only_context(changed_symbols: list[ChangedSymbol]) -> list[LabeledChunkState]:
    """The "diff_only" ablation mode: no impact analysis, no graph expansion, no
    hybrid retrieval -- just the changed symbols' own (new) text, labeled the same way
    so citation handling and verify's evidence-validity rule still work unchanged.
    The breaking_change verify gate requires caller evidence, which never appears
    here, so breaking_change findings are structurally unavailable in this mode --
    that's the point of the ablation, not a bug. Pure function; no DB, no network."""
    context: list[LabeledChunkState] = []
    for i, symbol in enumerate(changed_symbols, start=1):
        start = symbol.new_start_line if symbol.new_start_line is not None else (symbol.old_start_line or 0)
        end = symbol.new_end_line if symbol.new_end_line is not None else (symbol.old_end_line or 0)
        context.append(
            LabeledChunkState(
                label=f"C{i}",
                chunk_id=str(symbol.indexed_chunk_id) if symbol.indexed_chunk_id is not None else "",
                file_path=symbol.file_path,
                symbol_name=symbol.symbol_name,
                start_line=start,
                end_line=end,
                source=symbol.new_source or "(no new source available, e.g. a removed symbol)",
                reason=f"changed:{symbol.change_type}",
                sources=["diff"],
                score=1.0,
            )
        )
    return context


def _diff_new_side_text(file_diff: FileDiff) -> str:
    """Best-effort stand-in for a file's full new content when the caller couldn't
    supply it: every new/context line visible across all of this file's hunks,
    concatenated. Strictly less complete than the real file (only the diff's own
    context lines are visible), but still per-file rather than per-symbol."""
    lines = []
    for hunk in file_diff.hunks:
        lines.extend(line.text for line in hunk.lines if line.tag != "remove")
    return "\n".join(lines)


def build_naive_context(
    file_diffs: list[FileDiff], full_file_contents: dict[str, str] | None = None
) -> list[LabeledChunkState]:
    """The "naive" ablation mode: simulates a per-file reviewer. No impact analysis,
    no graph expansion, no hybrid retrieval -- one chunk per changed file (not per
    symbol, unlike diff_only), holding that file's full new content when
    `full_file_contents` supplies it (keyed by the diff's new-side path), or falling
    back to the diff's own visible new-side text for a file it doesn't have (e.g. a
    bare-diff review with no repo checkout or GitHub access to fetch from).

    No chunk here is ever tagged as a caller/callee (`reason` is always
    "naive_file_context"), so verify_findings must be called with
    `strict_gates=False` for this mode's findings -- the breaking_change and
    contract_change gates both require caller evidence that structurally cannot
    exist in this context, and gating on it anyway would make "naive" score zero on
    those categories by construction rather than by the model's own (lack of)
    rigor, which defeats its purpose as a baseline. Pure function; no DB, no network
    -- the caller is responsible for sourcing `full_file_contents`.
    """
    full_file_contents = full_file_contents or {}
    context: list[LabeledChunkState] = []
    label_num = 0
    for file_diff in file_diffs:
        if file_diff.is_binary or file_diff.is_deleted:
            continue
        path = file_diff.path
        content = full_file_contents.get(path) or _diff_new_side_text(file_diff)
        label_num += 1
        context.append(
            LabeledChunkState(
                label=f"C{label_num}",
                chunk_id="",
                file_path=path,
                symbol_name="",
                start_line=1,
                end_line=max(1, content.count("\n") + 1),
                source=content,
                reason="naive_file_context",
                sources=["naive"],
                score=1.0,
            )
        )
    return context
