from app.db.models import Repository, RepositoryStatus
from app.services.ingestion import ingest_repository
from tests.fakes import FakeEmbeddings


def test_ingest_repository_end_to_end(db_session, tiny_git_repo):
    repository = Repository(url=tiny_git_repo, name="tiny-repo", status=RepositoryStatus.PENDING)
    db_session.add(repository)
    db_session.commit()

    result = ingest_repository(db_session, repository.id, embeddings=FakeEmbeddings())

    assert result.skipped is False
    assert result.file_count == 1
    assert result.chunk_count == 2  # `add` and `main`

    db_session.refresh(repository)
    assert repository.status == RepositoryStatus.COMPLETED
    assert repository.last_commit_sha == result.commit_sha


def test_ingest_repository_is_idempotent_for_same_commit(db_session, tiny_git_repo):
    repository = Repository(url=tiny_git_repo, name="tiny-repo", status=RepositoryStatus.PENDING)
    db_session.add(repository)
    db_session.commit()

    first = ingest_repository(db_session, repository.id, embeddings=FakeEmbeddings())
    second = ingest_repository(db_session, repository.id, embeddings=FakeEmbeddings())

    assert first.skipped is False
    assert second.skipped is True
    assert second.chunk_count == first.chunk_count
