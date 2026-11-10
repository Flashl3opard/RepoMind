import enum
import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    TIMESTAMP,
    Computed,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.config import get_settings
from app.db.base import Base


class RepositoryStatus(enum.StrEnum):
    PENDING = "pending"
    CLONING = "cloning"
    PARSING = "parsing"
    EMBEDDING = "embedding"
    COMPLETED = "completed"
    FAILED = "failed"


class ChunkKind(enum.StrEnum):
    FUNCTION = "function"
    METHOD = "method"
    CLASS = "class"


class EdgeType(enum.StrEnum):
    IMPORTS = "imports"
    CALLS = "calls"


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class Repository(Base):
    __tablename__ = "repositories"

    id: Mapped[uuid.UUID] = _uuid_pk()
    url: Mapped[str] = mapped_column(String(2048), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[RepositoryStatus] = mapped_column(
        Enum(RepositoryStatus, name="repository_status"),
        nullable=False,
        default=RepositoryStatus.PENDING,
    )
    last_commit_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    files: Mapped[list["File"]] = relationship(back_populates="repository", cascade="all, delete-orphan")
    chunks: Mapped[list["Chunk"]] = relationship(back_populates="repository", cascade="all, delete-orphan")


class File(Base):
    __tablename__ = "files"
    __table_args__ = (UniqueConstraint("repository_id", "path", "commit_sha", name="uq_file_repo_path_commit"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    repository_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    path: Mapped[str] = mapped_column(String(2048), nullable=False)
    language: Mapped[str] = mapped_column(String(32), nullable=False)
    commit_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )

    repository: Mapped[Repository] = relationship(back_populates="files")
    chunks: Mapped[list["Chunk"]] = relationship(back_populates="file", cascade="all, delete-orphan")


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint(
            "file_id", "symbol_name", "start_line", "end_line", name="uq_chunk_file_symbol_span"
        ),
        Index("ix_chunks_content_tsv", "content_tsv", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("files.id", ondelete="CASCADE"), nullable=False, index=True
    )
    repository_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    symbol_name: Mapped[str] = mapped_column(String(512), nullable=False)
    kind: Mapped[ChunkKind] = mapped_column(Enum(ChunkKind, name="chunk_kind"), nullable=False)
    start_line: Mapped[int] = mapped_column(Integer, nullable=False)
    end_line: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_symbol: Mapped[str | None] = mapped_column(String(512), nullable=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    commit_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(get_settings().EMBEDDING_DIM), nullable=True
    )
    content_tsv: Mapped[str | None] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('english', source)", persisted=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )

    file: Mapped[File] = relationship(back_populates="chunks")
    repository: Mapped[Repository] = relationship(back_populates="chunks")
    outgoing_edges: Mapped[list["SymbolEdge"]] = relationship(
        back_populates="source_chunk", cascade="all, delete-orphan"
    )


class SymbolEdge(Base):
    __tablename__ = "symbol_edges"

    id: Mapped[uuid.UUID] = _uuid_pk()
    source_chunk_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chunks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_symbol: Mapped[str] = mapped_column(String(512), nullable=False)
    edge_type: Mapped[EdgeType] = mapped_column(Enum(EdgeType, name="symbol_edge_type"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )

    source_chunk: Mapped[Chunk] = relationship(back_populates="outgoing_edges")
