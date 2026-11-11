import uuid
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models import Chunk, EdgeType, File, SymbolEdge

MAX_AMBIGUOUS_CANDIDATES = 2


@dataclass(slots=True)
class CandidateMatch:
    chunk_id: uuid.UUID
    file_id: uuid.UUID
    file_path: str


@dataclass(slots=True)
class ResolvedTarget:
    chunk_id: uuid.UUID
    ambiguous: bool


def _file_module_candidates(file_path: str) -> set[str]:
    """Plausible module names a file could be imported as, e.g.
    "app/services/ingestion.py" -> {"ingestion", "services.ingestion", "app.services.ingestion"}."""
    without_suffix = file_path[: -len(".py")] if file_path.endswith(".py") else file_path
    without_suffix = without_suffix.removesuffix(".ts").removesuffix(".tsx")
    parts = [p for p in without_suffix.replace("\\", "/").split("/") if p]
    if not parts:
        return set()
    return {".".join(parts[i:]) for i in range(len(parts))} | {parts[-1]}


def _import_references_file(import_str: str, file_path: str) -> bool:
    file_candidates = _file_module_candidates(file_path)
    import_parts = import_str.split(".")
    for i in range(1, len(import_parts) + 1):
        if ".".join(import_parts[:i]) in file_candidates:
            return True
    return False


def select_preferred_targets(
    source_file_id: uuid.UUID,
    source_file_imports: set[str],
    candidates: list[CandidateMatch],
) -> list[ResolvedTarget]:
    """Pick the best-tier candidate(s) a symbol name resolves to.

    Preference order: (0) a candidate whose file matches one of the source file's
    imports, (1) a candidate in the same file as the source, (2) anything else. Ties
    within the winning tier are kept (at most `MAX_AMBIGUOUS_CANDIDATES`) and marked
    ambiguous; a lone winner is not ambiguous. Never raises on an empty candidate list.
    """
    if not candidates:
        return []

    def tier(candidate: CandidateMatch) -> int:
        if any(_import_references_file(imp, candidate.file_path) for imp in source_file_imports):
            return 0
        if candidate.file_id == source_file_id:
            return 1
        return 2

    best_tier = min(tier(c) for c in candidates)
    winners = [c for c in candidates if tier(c) == best_tier]
    ambiguous = len(winners) > 1
    chosen = winners[:MAX_AMBIGUOUS_CANDIDATES] if ambiguous else winners[:1]
    return [ResolvedTarget(chunk_id=c.chunk_id, ambiguous=ambiguous) for c in chosen]


def _last_segment(symbol: str) -> str:
    return symbol.rsplit(".", 1)[-1]


def _imports_by_file(db: Session, repo_id: uuid.UUID) -> dict[uuid.UUID, set[str]]:
    rows = db.execute(
        select(Chunk.file_id, SymbolEdge.target_symbol)
        .join(SymbolEdge, SymbolEdge.source_chunk_id == Chunk.id)
        .where(Chunk.repository_id == repo_id, SymbolEdge.edge_type == EdgeType.IMPORTS)
    ).all()
    result: dict[uuid.UUID, set[str]] = defaultdict(set)
    for file_id, target in rows:
        result[file_id].add(target)
    return result


def resolve_edges(
    db: Session,
    repo_id: uuid.UUID,
    chunk_ids: list[uuid.UUID],
    edge_types: tuple[EdgeType, ...] | None = None,
) -> dict[uuid.UUID, list[ResolvedTarget]]:
    """For each SymbolEdge whose source is in `chunk_ids`, resolve `target_symbol` to
    chunk(s) in the same repository. Returns {source_chunk_id: [ResolvedTarget, ...]},
    omitting edges that resolve to nothing. Never raises on an unresolved name."""
    if not chunk_ids:
        return {}

    source_chunks = db.scalars(select(Chunk).where(Chunk.id.in_(chunk_ids))).all()
    source_by_id = {c.id: c for c in source_chunks}
    if not source_by_id:
        return {}

    edge_query = select(SymbolEdge).where(SymbolEdge.source_chunk_id.in_(chunk_ids))
    if edge_types:
        edge_query = edge_query.where(SymbolEdge.edge_type.in_(edge_types))
    edges = db.scalars(edge_query).all()
    if not edges:
        return {}

    all_chunks = db.scalars(select(Chunk).where(Chunk.repository_id == repo_id)).all()
    files = db.scalars(select(File).where(File.repository_id == repo_id)).all()
    file_path_by_id = {f.id: f.path for f in files}

    by_symbol: dict[str, list[Chunk]] = defaultdict(list)
    for c in all_chunks:
        by_symbol[c.symbol_name].append(c)

    imports_by_file = _imports_by_file(db, repo_id)

    resolved: dict[uuid.UUID, list[ResolvedTarget]] = defaultdict(list)
    for edge in edges:
        source = source_by_id.get(edge.source_chunk_id)
        if source is None:
            continue

        matches = by_symbol.get(edge.target_symbol) or by_symbol.get(_last_segment(edge.target_symbol), [])
        matches = [c for c in matches if c.id != source.id]
        if not matches:
            continue

        candidates = [
            CandidateMatch(chunk_id=c.id, file_id=c.file_id, file_path=file_path_by_id.get(c.file_id, ""))
            for c in matches
        ]
        targets = select_preferred_targets(source.file_id, imports_by_file.get(source.file_id, set()), candidates)
        resolved[edge.source_chunk_id].extend(targets)

    return dict(resolved)


@dataclass(slots=True)
class ExpandedChunk:
    chunk: Chunk
    reason: str  # "callee_of:<symbol>" | "caller_of:<symbol>"
    link_count: int


def expand_context(
    db: Session, repo_id: uuid.UUID, seed_chunks: list[Chunk], max_extra: int = 6
) -> list[ExpandedChunk]:
    """One-hop callees and callers of `seed_chunks`, deduplicated and ranked by how many
    distinct seed chunks link to each, capped at `max_extra`."""
    if not seed_chunks:
        return []

    seed_ids = {c.id for c in seed_chunks}
    seed_by_id = {c.id: c for c in seed_chunks}
    seed_symbol_to_id = {c.symbol_name: c.id for c in seed_chunks}

    # Callees: seeds' own CALLS edges, resolved to target chunks.
    links: dict[uuid.UUID, list[tuple[uuid.UUID, str]]] = defaultdict(list)
    resolved_callees = resolve_edges(db, repo_id, list(seed_ids), edge_types=(EdgeType.CALLS,))
    for source_id, targets in resolved_callees.items():
        seed_symbol = seed_by_id[source_id].symbol_name
        for target in targets:
            if target.chunk_id in seed_ids:
                continue
            links[target.chunk_id].append((source_id, f"callee_of:{seed_symbol}"))

    # Callers: other chunks in the repo whose CALLS edge targets a seed's symbol name.
    caller_rows = db.scalars(
        select(SymbolEdge)
        .join(Chunk, SymbolEdge.source_chunk_id == Chunk.id)
        .where(Chunk.repository_id == repo_id, SymbolEdge.edge_type == EdgeType.CALLS)
    ).all()
    for edge in caller_rows:
        if edge.source_chunk_id in seed_ids:
            continue
        matched_seed_id = seed_symbol_to_id.get(edge.target_symbol) or seed_symbol_to_id.get(
            _last_segment(edge.target_symbol)
        )
        if matched_seed_id is None:
            continue
        seed_symbol = seed_by_id[matched_seed_id].symbol_name
        links[edge.source_chunk_id].append((matched_seed_id, f"caller_of:{seed_symbol}"))

    ranked = sorted(links.items(), key=lambda kv: len(kv[1]), reverse=True)[:max_extra]
    if not ranked:
        return []

    extra_ids = [chunk_id for chunk_id, _ in ranked]
    chunks_by_id = {
        c.id: c
        for c in db.scalars(
            select(Chunk).where(Chunk.id.in_(extra_ids)).options(selectinload(Chunk.file))
        ).all()
    }

    results: list[ExpandedChunk] = []
    for chunk_id, chunk_links in ranked:
        chunk = chunks_by_id.get(chunk_id)
        if chunk is None:
            continue
        results.append(ExpandedChunk(chunk=chunk, reason=chunk_links[0][1], link_count=len(chunk_links)))
    return results
