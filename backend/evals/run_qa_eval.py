"""Baseline Q&A eval.

Ingests a small fixture repo, asks every question in qa_questions.yaml against the
real `run_qa()` pipeline (same code path as `POST /repos/{id}/ask`), and reports hit
rate (did any citation land in that question's expected_files), average latency, and
how many answers came back low-confidence (ungrounded). This is a seed to improve
against later, not a full eval harness -- do not over-build on top of it.

Usage (from backend/):
    uv run python evals/run_qa_eval.py

Requires a reachable Postgres+pgvector at DATABASE_URL and a configured API key for
whichever EMBEDDING_PROVIDER / CHAT_PROVIDER is set (OPENAI_API_KEY or GOOGLE_API_KEY).
"""

import subprocess
import sys
import tempfile
import time
from pathlib import Path

import yaml
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.agents.llm import build_chat_model, build_verify_model  # noqa: E402
from app.agents.qa import run_qa  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import models  # noqa: E402,F401 - registers tables on Base.metadata
from app.db.base import Base  # noqa: E402
from app.db.models import Repository, RepositoryStatus  # noqa: E402
from app.services.embeddings import get_embeddings  # noqa: E402
from app.services.ingestion import ingest_repository  # noqa: E402

QUESTIONS_PATH = Path(__file__).parent / "qa_questions.yaml"

FIXTURE_FILES = {
    "calculator.py": (
        "def add(a, b):\n"
        "    return a + b\n"
        "\n\n"
        "def subtract(a, b):\n"
        "    return a - b\n"
        "\n\n"
        "def multiply(a, b):\n"
        "    return a * b\n"
        "\n\n"
        "def divide(a, b):\n"
        '    if b == 0:\n        raise ValueError("division by zero")\n'
        "    return a / b\n"
    ),
    "utils.py": 'def format_result(value):\n    return f"Result: {value}"\n',
    "main.py": (
        "from calculator import add, subtract, multiply, divide\n"
        "from utils import format_result\n"
        "\n\n"
        "def main():\n"
        "    total = add(1, 2)\n"
        "    total = subtract(total, 1)\n"
        "    total = multiply(total, 4)\n"
        "    total = divide(total, 2)\n"
        "    return format_result(total)\n"
    ),
}


def _build_fixture_repo(tmp_dir: Path) -> str:
    repo_dir = tmp_dir / "eval-fixture-repo"
    repo_dir.mkdir()
    for name, content in FIXTURE_FILES.items():
        (repo_dir / name).write_text(content)

    def run(*args: str) -> None:
        subprocess.run(["git", *args], cwd=repo_dir, check=True, capture_output=True, text=True)

    run("init", "-q")
    run("config", "user.email", "eval@example.com")
    run("config", "user.name", "Eval")
    run("add", ".")
    run("commit", "-q", "-m", "fixture")
    return str(repo_dir)


def main() -> None:
    settings = get_settings()
    engine = create_engine(settings.DATABASE_URL)
    Base.metadata.create_all(engine)
    db = Session(bind=engine)

    questions = yaml.safe_load(QUESTIONS_PATH.read_text())
    embeddings = get_embeddings(settings)
    chat_model = build_chat_model(settings)
    verify_model = build_verify_model(settings)

    with tempfile.TemporaryDirectory() as tmp:
        repo_url = _build_fixture_repo(Path(tmp))
        repository = Repository(url=repo_url, name="eval-fixture-repo", status=RepositoryStatus.PENDING)
        db.add(repository)
        db.commit()
        ingest_repository(db, repository.id, embeddings=embeddings)
        db.refresh(repository)

        hits = 0
        ungrounded = 0
        latencies: list[float] = []

        try:
            for q in questions:
                start = time.perf_counter()
                result = run_qa(
                    db,
                    repository.id,
                    q["question"],
                    embeddings=embeddings,
                    chat_model=chat_model,
                    verify_model=verify_model,
                    top_k=settings.QA_DEFAULT_TOP_K,
                    max_expanded=settings.QA_MAX_EXPANDED_CHUNKS,
                    max_attempts=settings.QA_MAX_ATTEMPTS,
                )
                elapsed = time.perf_counter() - start
                latencies.append(elapsed)

                cited_files = {c["file_path"] for c in result.citations}
                expected = set(q["expected_files"])
                hit = bool(cited_files & expected)
                hits += int(hit)
                ungrounded += int(result.confidence == "low")

                print(
                    f"[{'HIT' if hit else 'MISS'}] (#{q['id']}, {elapsed:.2f}s, "
                    f"{result.confidence}) {q['question']}"
                )
                if not hit:
                    print(f"         expected one of {expected}, cited {cited_files or '(none)'}")

            n = len(questions)
            print()
            print(f"hit rate: {hits}/{n} ({hits / n:.0%})")
            print(f"average latency: {sum(latencies) / n:.2f}s")
            print(f"ungrounded answers: {ungrounded}/{n}")
        finally:
            db.delete(repository)
            db.commit()


if __name__ == "__main__":
    main()
