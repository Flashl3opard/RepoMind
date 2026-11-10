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
