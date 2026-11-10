"""initial schema: repositories, files, chunks, symbol_edges

Revision ID: 0001
Revises:
Create Date: 2026-11-10

"""
from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Must match Settings.EMBEDDING_DIM. Switching embedding providers to a model with a
# different dimension requires a follow-up migration that ALTERs this column's type.
EMBEDDING_DIM = 1536


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "repositories",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.Column("name", sa.String(512), nullable=False),
        sa.Column(
            "status",
            sa.Enum("pending", "cloning", "parsing", "embedding", "completed", "failed", name="repository_status"),
            nullable=False,
        ),
        sa.Column("last_commit_sha", sa.String(64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_repositories_url", "repositories", ["url"])

    op.create_table(
        "files",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "repository_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("repositories.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("path", sa.String(2048), nullable=False),
        sa.Column("language", sa.String(32), nullable=False),
        sa.Column("commit_sha", sa.String(64), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("repository_id", "path", "commit_sha", name="uq_file_repo_path_commit"),
    )
    op.create_index("ix_files_repository_id", "files", ["repository_id"])

    op.create_table(
        "chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "file_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("files.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "repository_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("repositories.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("symbol_name", sa.String(512), nullable=False),
        sa.Column("kind", sa.Enum("function", "method", "class", name="chunk_kind"), nullable=False),
        sa.Column("start_line", sa.Integer(), nullable=False),
        sa.Column("end_line", sa.Integer(), nullable=False),
        sa.Column("parent_symbol", sa.String(512), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("commit_sha", sa.String(64), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.Vector(EMBEDDING_DIM), nullable=True),
        sa.Column(
            "content_tsv",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('english', source)", persisted=True),
            nullable=True,
        ),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("file_id", "symbol_name", "start_line", "end_line", name="uq_chunk_file_symbol_span"),
    )
    op.create_index("ix_chunks_file_id", "chunks", ["file_id"])
    op.create_index("ix_chunks_repository_id", "chunks", ["repository_id"])
    op.create_index("ix_chunks_content_tsv", "chunks", ["content_tsv"], postgresql_using="gin")
    op.execute("CREATE INDEX ix_chunks_embedding ON chunks USING hnsw (embedding vector_cosine_ops)")

    op.create_table(
        "symbol_edges",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "source_chunk_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("chunks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("target_symbol", sa.String(512), nullable=False),
        sa.Column("edge_type", sa.Enum("imports", "calls", name="symbol_edge_type"), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_symbol_edges_source_chunk_id", "symbol_edges", ["source_chunk_id"])


def downgrade() -> None:
    op.drop_table("symbol_edges")
    op.drop_index("ix_chunks_embedding", table_name="chunks")
    op.drop_index("ix_chunks_content_tsv", table_name="chunks")
    op.drop_index("ix_chunks_repository_id", table_name="chunks")
    op.drop_index("ix_chunks_file_id", table_name="chunks")
    op.drop_table("chunks")
    op.drop_index("ix_files_repository_id", table_name="files")
    op.drop_table("files")
    op.drop_index("ix_repositories_url", table_name="repositories")
    op.drop_table("repositories")
    op.execute("DROP TYPE IF EXISTS symbol_edge_type")
    op.execute("DROP TYPE IF EXISTS chunk_kind")
    op.execute("DROP TYPE IF EXISTS repository_status")
