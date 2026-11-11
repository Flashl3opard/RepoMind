from sqlalchemy import text
from sqlalchemy.engine import Engine


class EmbeddingDimensionMismatch(RuntimeError):
    pass


def assert_embedding_dimension_matches_db(engine: Engine, expected_dim: int) -> None:
    """Fail fast if `chunks.embedding`'s pgvector width doesn't match `Settings.EMBEDDING_DIM`."""
    with engine.connect() as conn:
        actual_dim = conn.execute(
            text(
                "SELECT atttypmod FROM pg_attribute "
                "WHERE attrelid = 'chunks'::regclass AND attname = 'embedding'"
            )
        ).scalar()

    if actual_dim is None:
        raise EmbeddingDimensionMismatch(
            "chunks.embedding column not found; run `alembic upgrade head` before starting the app."
        )
    if actual_dim != expected_dim:
        raise EmbeddingDimensionMismatch(
            f"EMBEDDING_DIM is configured as {expected_dim}, but the chunks.embedding column in "
            f"the database is vector({actual_dim}). Either fix EMBEDDING_DIM or write a migration "
            f"that ALTERs chunks.embedding to vector({expected_dim})."
        )
