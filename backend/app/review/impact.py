"""Cross-file impact analysis for a changed symbol: callers, callees, and referencing
tests, reusing the existing symbol-edge resolution and one-hop graph expansion
(`app/retrieval/graph.py`). DB-backed; the "is this a test file" / "is this caller
touched by the PR" checks are pure and unit-tested separately from the DB plumbing.
"""

import re
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models import Chunk, File
from app.retrieval.graph import expand_context
from app.review.diff_parser import range_overlaps_any
from app.review.map_changes import ChangedSymbol

_TEST_FILE_RE = re.compile(r"(^|/)(test_[^/]+\.py|[^/]+_test\.py|[^/]+\.(?:test|spec)\.tsx?)$")


def is_test_file(path: str) -> bool:
    return bool(_TEST_FILE_RE.search(path.replace("\\", "/")))


@dataclass(slots=True)
class CallerInfo:
    chunk: Chunk
    touched_by_pr: bool  # False = this caller wasn't updated anywhere in the same PR


@dataclass(slots=True)
class ImpactResult:
    symbol: ChangedSymbol
    callees: list[Chunk]
    callers: list[CallerInfo]
    referencing_tests: list[Chunk]


def find_referencing_tests(db: Session, repo_id: uuid.UUID, symbol_name: str) -> list[Chunk]:
    """Test-file chunks whose source mentions `symbol_name` as a whole word."""
    candidates = db.scalars(
        select(Chunk)
        .join(File, Chunk.file_id == File.id)
        .where(Chunk.repository_id == repo_id, File.path.ilike("%test%"))
        .options(selectinload(Chunk.file))
    ).all()
    pattern = re.compile(rf"\b{re.escape(symbol_name)}\b")
    return [c for c in candidates if is_test_file(c.file.path) and pattern.search(c.source)]


def analyze_impact(
    db: Session,
    repo_id: uuid.UUID,
    changed_symbol: ChangedSymbol,
    old_side_ranges_by_file: dict[str, list[tuple[int, int]]],
    max_extra: int = 6,
) -> ImpactResult | None:
    """None when the symbol has no indexed chunk to expand from (e.g. a brand-new
    symbol can't have existing callers/callees yet)."""
    if changed_symbol.indexed_chunk_id is None:
        return None

    seed_chunk = db.scalars(
        select(Chunk).where(Chunk.id == changed_symbol.indexed_chunk_id).options(selectinload(Chunk.file))
    ).first()
    if seed_chunk is None:
        return None

    expanded = expand_context(db, repo_id, [seed_chunk], max_extra=max_extra)

    callees: list[Chunk] = []
    callers: list[CallerInfo] = []
    for item in expanded:
        if item.reason.startswith("callee_of:"):
            callees.append(item.chunk)
        elif item.reason.startswith("caller_of:"):
            ranges = old_side_ranges_by_file.get(item.chunk.file.path, [])
            touched = range_overlaps_any(item.chunk.start_line, item.chunk.end_line, ranges)
            callers.append(CallerInfo(chunk=item.chunk, touched_by_pr=touched))

    tests = find_referencing_tests(db, repo_id, changed_symbol.symbol_name)

    return ImpactResult(symbol=changed_symbol, callees=callees, callers=callers, referencing_tests=tests)
