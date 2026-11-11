import uuid
from collections import defaultdict
from dataclasses import dataclass

from langchain_core.embeddings import Embeddings
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models import Chunk
from app.retrieval.keyword import keyword_search
from app.retrieval.rrf import reciprocal_rank_fusion
from app.retrieval.vector import vector_search


@dataclass(slots=True)
class RetrievedChunk:
    chunk: Chunk
    score: float
    sources: list[str]  # e.g. ["vector"], ["keyword"], or ["vector", "keyword"]


def hybrid_search(
    db: Session,
    repo_id: uuid.UUID,
    query: str,
    embeddings: Embeddings,
    top_k: int = 8,
) -> list[RetrievedChunk]:
    """Vector + keyword retrieval, fused with RRF."""
    query_embedding = embeddings.embed_query(query)
    vector_ids = vector_search(db, repo_id, query_embedding, k=top_k * 2)
    keyword_ids = keyword_search(db, repo_id, query, k=top_k * 2)

    fused = reciprocal_rank_fusion([vector_ids, keyword_ids])
    top_ids = [chunk_id for chunk_id, _ in fused[:top_k]]
    if not top_ids:
        return []

    chunks_by_id = {
        c.id: c
        for c in db.scalars(
            select(Chunk).where(Chunk.id.in_(top_ids)).options(selectinload(Chunk.file))
        ).all()
    }
    score_by_id = dict(fused)

    source_sets: dict[uuid.UUID, set[str]] = defaultdict(set)
    for chunk_id in vector_ids:
        source_sets[chunk_id].add("vector")
    for chunk_id in keyword_ids:
        source_sets[chunk_id].add("keyword")

    results: list[RetrievedChunk] = []
    for chunk_id in top_ids:
        chunk = chunks_by_id.get(chunk_id)
        if chunk is None:
            continue
        results.append(
            RetrievedChunk(chunk=chunk, score=score_by_id[chunk_id], sources=sorted(source_sets[chunk_id]))
        )
    return results


def merge_retrieved(result_sets: list[list[RetrievedChunk]], top_k: int = 8) -> list[RetrievedChunk]:
    """RRF-merge several already-ranked RetrievedChunk lists (e.g. one per query variant)."""
    rankings = [[r.chunk.id for r in results] for results in result_sets]
    fused = reciprocal_rank_fusion(rankings)

    base_by_id: dict[uuid.UUID, RetrievedChunk] = {}
    source_union: dict[uuid.UUID, set[str]] = defaultdict(set)
    for results in result_sets:
        for r in results:
            source_union[r.chunk.id].update(r.sources)
            base_by_id.setdefault(r.chunk.id, r)

    merged: list[RetrievedChunk] = []
    for chunk_id, score in fused[:top_k]:
        base = base_by_id.get(chunk_id)
        if base is None:
            continue
        merged.append(RetrievedChunk(chunk=base.chunk, score=score, sources=sorted(source_union[chunk_id])))
    return merged
