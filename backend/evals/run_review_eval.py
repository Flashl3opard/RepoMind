"""Baseline PR-review eval.

Ingests the shared fixture repo, then runs every synthetic PR diff in
evals/review_cases/*.diff against the real `run_review()` pipeline (same code path as
`POST /repos/{id}/review`), comparing the verified findings against that case's
expected (file, category) pairs in the matching *.yaml file. Reports recall of
expected findings, how many unexpected findings showed up, and latency per case. A
baseline seed to improve against later -- do not over-build on top of it.

Usage (from backend/):
    uv run python evals/run_review_eval.py

Requires a reachable Postgres+pgvector at DATABASE_URL and a configured API key for
whichever EMBEDDING_PROVIDER / CHAT_PROVIDER is set (OPENAI_API_KEY or GOOGLE_API_KEY).
"""

import sys
import tempfile
import time
from pathlib import Path

import yaml
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.agents.llm import build_chat_model  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import models  # noqa: E402,F401 - registers tables on Base.metadata
from app.db.base import Base  # noqa: E402
from app.db.models import Repository, RepositoryStatus  # noqa: E402
from app.review.graph import run_review  # noqa: E402
from app.services.embeddings import get_embeddings  # noqa: E402
from app.services.ingestion import ingest_repository  # noqa: E402
from evals.fixture_repo import build_fixture_repo  # noqa: E402

CASES_DIR = Path(__file__).parent / "review_cases"


def load_cases() -> list[dict]:
    cases = []
    for diff_path in sorted(CASES_DIR.glob("*.diff")):
        yaml_path = diff_path.with_suffix(".yaml")
        spec = yaml.safe_load(yaml_path.read_text()) if yaml_path.exists() else {"expected": []}
        cases.append(
            {
                "name": diff_path.stem,
                "diff": diff_path.read_text(),
                "description": spec.get("description", ""),
                "expected": spec.get("expected", []),
            }
        )
    return cases


def _matches(finding: dict, expected: dict) -> bool:
    return finding["file"] == expected["file"] and finding["category"] == expected["category"]


def main() -> None:
    settings = get_settings()
    engine = create_engine(settings.DATABASE_URL)
    Base.metadata.create_all(engine)
    db = Session(bind=engine)

    cases = load_cases()
    embeddings = get_embeddings(settings)
    chat_model = build_chat_model(settings, timeout=settings.REVIEW_LLM_TIMEOUT_SECONDS)

    with tempfile.TemporaryDirectory() as tmp:
        repo_url = build_fixture_repo(Path(tmp))
        repository = Repository(url=repo_url, name="review-eval-fixture-repo", status=RepositoryStatus.PENDING)
        db.add(repository)
        db.commit()
        ingest_repository(db, repository.id, embeddings=embeddings)
        db.refresh(repository)

        total_expected = 0
        total_hits = 0
        total_unexpected = 0
        latencies: list[float] = []

        try:
            for case in cases:
                start = time.perf_counter()
                result = run_review(
                    db,
                    repository,
                    case["diff"],
                    embeddings=embeddings,
                    chat_model=chat_model,
                    max_files=settings.REVIEW_MAX_FILES,
                    max_diff_bytes=settings.REVIEW_MAX_DIFF_BYTES,
                    max_diff_tokens=settings.REVIEW_MAX_DIFF_TOKENS,
                    max_expanded_per_symbol=settings.REVIEW_MAX_EXPANDED_PER_SYMBOL,
                    max_context_tokens=settings.REVIEW_MAX_CONTEXT_TOKENS,
                    max_findings_per_file=settings.REVIEW_MAX_FINDINGS_PER_FILE,
                    retrieval_top_k=settings.REVIEW_RETRIEVAL_TOP_K,
                )
                elapsed = time.perf_counter() - start
                latencies.append(elapsed)

                findings = [dict(f) for f in result.verified_findings]
                expected = case["expected"]
                hits = sum(1 for e in expected if any(_matches(f, e) for f in findings))
                unexpected = sum(1 for f in findings if not any(_matches(f, e) for e in expected))

                total_expected += len(expected)
                total_hits += hits
                total_unexpected += unexpected

                print(f"--- {case['name']} ({elapsed:.2f}s, risk={result.risk_level}) ---")
                print(f"    expected {len(expected)}, hit {hits}; unexpected findings: {unexpected}")
                for f in findings:
                    print(f"    [{f['severity']}/{f['category']}] {f['file']}:{f['start_line']}-{f['end_line']} {f['message']}")

            print()
            recall = total_hits / total_expected if total_expected else 1.0
            print(f"recall: {total_hits}/{total_expected} ({recall:.0%})")
            print(f"unexpected findings (total): {total_unexpected}")
            print(f"average latency: {sum(latencies) / len(latencies):.2f}s")
        finally:
            db.delete(repository)
            db.commit()


if __name__ == "__main__":
    main()
