import os
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.db import models  # noqa: F401 - registers tables on Base.metadata
from app.db.base import Base

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://repomind:repomind@localhost:5432/repomind"
)


@pytest.fixture
def db_session() -> Iterator[Session]:
    """A real Postgres+pgvector session for integration tests. Requires the stack from
    `docker-compose up -d db` (or TEST_DATABASE_URL pointed at one); skips otherwise."""
    # connect_timeout keeps an unreachable DB from hanging the test suite indefinitely
    # (a dropped/filtered connection attempt can otherwise block far longer than a
    # refused one).
    engine = create_engine(TEST_DATABASE_URL, connect_args={"connect_timeout": 5})
    try:
        with engine.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.commit()
    except Exception as exc:
        engine.dispose()
        pytest.skip(f"Postgres with pgvector not reachable at {TEST_DATABASE_URL}: {exc}")

    Base.metadata.create_all(engine)
    session = Session(bind=engine)
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def tiny_git_repo(tmp_path: Path) -> str:
    """A minimal local git repo with one commit, usable as a clone source."""
    repo_dir = tmp_path / "tiny-repo"
    repo_dir.mkdir()
    (repo_dir / "main.py").write_text(
        "def add(a, b):\n    return a + b\n\n\ndef main():\n    return add(1, 2)\n"
    )

    def run(*args: str) -> None:
        subprocess.run(["git", *args], cwd=repo_dir, check=True, capture_output=True, text=True)

    run("init", "-q")
    run("config", "user.email", "test@example.com")
    run("config", "user.name", "Test")
    run("add", ".")
    run("commit", "-q", "-m", "initial commit")

    return str(repo_dir)


@pytest.fixture
def qa_fixture_repo(tmp_path: Path) -> str:
    """A couple of related functions across two files, for exercising hybrid retrieval
    and one-hop graph expansion (main calls add and subtract)."""
    repo_dir = tmp_path / "qa-fixture-repo"
    repo_dir.mkdir()
    (repo_dir / "calculator.py").write_text(
        "def add(a, b):\n"
        "    return a + b\n"
        "\n\n"
        "def subtract(a, b):\n"
        "    return a - b\n"
    )
    (repo_dir / "main.py").write_text(
        "from calculator import add, subtract\n"
        "\n\n"
        "def main():\n"
        "    total = add(1, 2)\n"
        "    return subtract(total, 1)\n"
    )

    def run(*args: str) -> None:
        subprocess.run(["git", *args], cwd=repo_dir, check=True, capture_output=True, text=True)

    run("init", "-q")
    run("config", "user.email", "test@example.com")
    run("config", "user.name", "Test")
    run("add", ".")
    run("commit", "-q", "-m", "initial commit")

    return str(repo_dir)


@pytest.fixture
def ingested_repo(db_session: Session, qa_fixture_repo: str):
    """Ingests `qa_fixture_repo` with FakeEmbeddings and returns the completed Repository row."""
    from app.db.models import Repository, RepositoryStatus
    from app.services.ingestion import ingest_repository
    from tests.fakes import FakeEmbeddings

    repository = Repository(url=qa_fixture_repo, name="qa-fixture-repo", status=RepositoryStatus.PENDING)
    db_session.add(repository)
    db_session.commit()

    ingest_repository(db_session, repository.id, embeddings=FakeEmbeddings())
    db_session.refresh(repository)
    return repository
