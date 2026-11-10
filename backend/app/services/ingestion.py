import logging
import uuid
from dataclasses import dataclass
from pathlib import Path

from langchain_core.embeddings import Embeddings
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.models import Chunk, ChunkKind, EdgeType, File, Repository, RepositoryStatus, SymbolEdge
from app.parsing.base import ParsedChunk
from app.parsing.registry import get_parser_for_path
from app.services import cloner
from app.services.embeddings import embed_texts_in_batches, get_embeddings

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class IngestionResult:
    repository_id: uuid.UUID
    commit_sha: str
    file_count: int
    chunk_count: int
    skipped: bool  # True if this exact (repo, commit_sha) was already ingested


def ingest_repository(
    db: Session,
    repository_id: uuid.UUID,
    *,
    embeddings: Embeddings | None = None,
    settings: Settings | None = None,
) -> IngestionResult:
    """Clone -> parse -> embed -> persist. Safe to call repeatedly for the same repo;
    a commit that has already been fully ingested is a no-op."""
    settings = settings or get_settings()
    repository = db.get(Repository, repository_id)
    if repository is None:
        raise ValueError(f"Repository {repository_id} not found")

    cloned = None
    try:
        repository.status = RepositoryStatus.CLONING
        db.commit()
        cloned = cloner.clone_repository(repository.url)

        existing_files = db.scalar(
            select(func.count())
            .select_from(File)
            .where(File.repository_id == repository.id, File.commit_sha == cloned.commit_sha)
        )
        if existing_files:
            repository.status = RepositoryStatus.COMPLETED
            repository.last_commit_sha = cloned.commit_sha
            db.commit()
            chunk_count = (
                db.scalar(
                    select(func.count())
                    .select_from(Chunk)
                    .where(Chunk.repository_id == repository.id, Chunk.commit_sha == cloned.commit_sha)
                )
                or 0
            )
            return IngestionResult(repository.id, cloned.commit_sha, existing_files, chunk_count, skipped=True)

        repository.status = RepositoryStatus.PARSING
        db.commit()
        parsed_by_file = _parse_repo_files(cloned.path, settings)

        repository.status = RepositoryStatus.EMBEDDING
        db.commit()
        all_chunks = [chunk for chunks in parsed_by_file.values() for chunk in chunks]
        embeddings = embeddings or get_embeddings(settings)
        vectors = embed_texts_in_batches(
            embeddings, [c.source for c in all_chunks], settings.EMBEDDING_BATCH_SIZE
        )

        chunk_count = _persist(db, repository, cloned.commit_sha, parsed_by_file, vectors)

        repository.status = RepositoryStatus.COMPLETED
        repository.last_commit_sha = cloned.commit_sha
        db.commit()

        return IngestionResult(
            repository.id, cloned.commit_sha, len(parsed_by_file), chunk_count, skipped=False
        )
    except Exception as exc:  # noqa: BLE001 - surfaced via repository.error_message
        logger.exception("Ingestion failed for repository %s", repository_id)
        db.rollback()
        repository = db.get(Repository, repository_id)
        if repository is not None:
            repository.status = RepositoryStatus.FAILED
            repository.error_message = str(exc)
            db.commit()
        raise
    finally:
        if cloned is not None:
            cloner.cleanup(cloned)


def _parse_repo_files(repo_path: Path, settings: Settings) -> dict[str, list[ParsedChunk]]:
    results: dict[str, list[ParsedChunk]] = {}
    for path in sorted(repo_path.rglob("*")):
        if not path.is_file() or ".git" in path.parts:
            continue
        if path.suffix not in settings.SUPPORTED_EXTENSIONS:
            continue
        parser = get_parser_for_path(str(path))
        if parser is None:
            continue
        relative_path = path.relative_to(repo_path).as_posix()
        try:
            source = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        chunks = parser.parse(source, relative_path)
        if chunks:
            results[relative_path] = chunks
    return results


def _persist(
    db: Session,
    repository: Repository,
    commit_sha: str,
    parsed_by_file: dict[str, list[ParsedChunk]],
    vectors: list[list[float]],
) -> int:
    chunk_count = 0
    vector_iter = iter(vectors)

    for relative_path, parsed_chunks in parsed_by_file.items():
        parser = get_parser_for_path(relative_path)
        language = parser.language if parser is not None else "unknown"

        file_row = File(
            repository_id=repository.id, path=relative_path, language=language, commit_sha=commit_sha
        )
        db.add(file_row)
        db.flush()

        for parsed in parsed_chunks:
            chunk_row = Chunk(
                file_id=file_row.id,
                repository_id=repository.id,
                symbol_name=parsed.symbol_name,
                kind=ChunkKind(parsed.kind),
                start_line=parsed.start_line,
                end_line=parsed.end_line,
                parent_symbol=parsed.parent_symbol,
                source=parsed.source,
                commit_sha=commit_sha,
                embedding=next(vector_iter),
            )
            db.add(chunk_row)
            db.flush()

            for target in parsed.imports:
                db.add(SymbolEdge(source_chunk_id=chunk_row.id, target_symbol=target, edge_type=EdgeType.IMPORTS))
            for target in parsed.calls:
                db.add(SymbolEdge(source_chunk_id=chunk_row.id, target_symbol=target, edge_type=EdgeType.CALLS))

            chunk_count += 1

    db.commit()
    return chunk_count
