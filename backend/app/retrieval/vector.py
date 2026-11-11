import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Chunk


def vector_search(db: Session, repo_id: uuid.UUID, query_embedding: list[float], k: int = 8) -> list[uuid.UUID]:
    """Rank chunk ids by pgvector cosine distance to `query_embedding` (closest first)."""
    distance = Chunk.embedding.cosine_distance(query_embedding)
    rows = db.scalars(
        select(Chunk.id)
        .where(Chunk.repository_id == repo_id, Chunk.embedding.is_not(None))
        .order_by(distance)
        .limit(k)
    ).all()
    return list(rows)
