"""Runner for the PR-review context-mode ablation benchmark.

For each case in a cases directory (produced by generate.py), runs run_review() in
both "full" and "diff_only" context modes against the same ingested repo, caching LLM
responses on disk (see llm_cache.py) so reruns without a prompt/model change are
free. Reports recall on positive cases, false-positive rate on negative cases,
evidence-validity rate, average latency, and a rough estimated-token cost, broken
down by mutation_type, plus a full-vs-diff_only comparison table. Writes
bench/results/<timestamp>.json and bench/results/latest.md.

Usage:
    uv run python -m evals.bench.run --repo /path/to/repo --cases-dir evals/bench/cases/<repo>

Requires a reachable Postgres+pgvector at DATABASE_URL and a configured API key for
whichever EMBEDDING_PROVIDER / CHAT_PROVIDER is set.
"""

import argparse
import json
import sys
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import yaml
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.agents.llm import build_chat_model  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import models  # noqa: E402,F401 - registers tables on Base.metadata
from app.db.base import Base  # noqa: E402
from app.db.models import Repository, RepositoryStatus  # noqa: E402
from app.review.context_retrieval import estimate_tokens  # noqa: E402
from app.review.graph import ReviewResult, run_review  # noqa: E402
from app.services.embeddings import get_embeddings  # noqa: E402
from app.services.ingestion import ingest_repository  # noqa: E402
from evals.bench.llm_cache import CachingChatModel  # noqa: E402

CONTEXT_MODES = ("full", "diff_only")
RESULTS_DIR = Path(__file__).parent / "results"


def load_cases(cases_dir: Path) -> list[dict]:
    cases = []
    for case_dir in sorted(p for p in cases_dir.iterdir() if p.is_dir()):
        diff_path = case_dir / "pr.diff"
        expected_path = case_dir / "expected.yaml"
        if not diff_path.exists() or not expected_path.exists():
            continue
        cases.append(
            {"case_id": case_dir.name, "diff": diff_path.read_text(), "expected": yaml.safe_load(expected_path.read_text())}
        )
    return cases


def run_one(db: Session, repository: Repository, case: dict, mode: str, embeddings, chat_model, settings) -> tuple[ReviewResult | None, float, str | None]:
    start = time.perf_counter()
    try:
        result = run_review(
            db, repository, case["diff"], embeddings=embeddings, chat_model=chat_model,
            max_files=settings.REVIEW_MAX_FILES, max_diff_bytes=settings.REVIEW_MAX_DIFF_BYTES,
            max_diff_tokens=settings.REVIEW_MAX_DIFF_TOKENS, max_expanded_per_symbol=settings.REVIEW_MAX_EXPANDED_PER_SYMBOL,
            max_context_tokens=settings.REVIEW_MAX_CONTEXT_TOKENS, max_findings_per_file=settings.REVIEW_MAX_FINDINGS_PER_FILE,
            retrieval_top_k=settings.REVIEW_RETRIEVAL_TOP_K, context_mode=mode,
        )
        error = None
    except Exception as exc:  # noqa: BLE001 - recorded in the results, not fatal to the sweep
        result = None
        error = str(exc)
    elapsed = time.perf_counter() - start
    return result, elapsed, error


def evaluate(case: dict, result: ReviewResult | None, mode: str, elapsed: float, error: str | None) -> dict:
    expected = case["expected"]
    findings = result.verified_findings if result else []
    context_by_label = {c["label"]: c for c in result.context} if result else {}

    hit = None
    if not expected["is_negative"]:
        hit = False
        for finding in findings:
            if finding["file"] != expected["changed_file"]:
                continue
            cited_files = {
                context_by_label[label]["file_path"] for label in finding["evidence"] if label in context_by_label
            }
            if cited_files & set(expected["expected_caller_files"]):
                hit = True
                break

    false_positive = None
    if expected["is_negative"]:
        false_positive = any(f["category"] == "breaking_change" and f["file"] == expected["changed_file"] for f in findings)

    valid_labels = set(context_by_label)
    evidence_valid = all(all(label in valid_labels for label in f["evidence"]) for f in findings)

    estimated_tokens = sum(estimate_tokens(c["source"]) for c in (result.context if result else []))

    return {
        "case_id": case["case_id"],
        "mode": mode,
        "mutation_type": expected["mutation_type"],
        "is_negative": expected["is_negative"],
        "hit": hit,
        "false_positive": false_positive,
        "evidence_valid": evidence_valid,
        "finding_count": len(findings),
        "latency_seconds": elapsed,
        "estimated_tokens": estimated_tokens,
        "error": error,
    }


def _rate(values: list[bool]) -> float | None:
    return sum(values) / len(values) if values else None


def summarize(rows: list[dict]) -> dict:
    by_mode: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_mode[row["mode"]].append(row)

    summary = {}
    for mode, mode_rows in by_mode.items():
        positives = [r for r in mode_rows if not r["is_negative"]]
        negatives = [r for r in mode_rows if r["is_negative"]]
        summary[mode] = {
            "recall": _rate([bool(r["hit"]) for r in positives]),
            "false_positive_rate": _rate([bool(r["false_positive"]) for r in negatives]),
            "evidence_validity_rate": _rate([r["evidence_valid"] for r in mode_rows]),
            "avg_latency_seconds": sum(r["latency_seconds"] for r in mode_rows) / len(mode_rows) if mode_rows else None,
            "avg_estimated_tokens": sum(r["estimated_tokens"] for r in mode_rows) / len(mode_rows) if mode_rows else None,
            "error_count": sum(1 for r in mode_rows if r["error"]),
            "case_count": len(mode_rows),
            "by_mutation_type": _by_mutation_type(mode_rows),
        }
    return summary


def _by_mutation_type(mode_rows: list[dict]) -> dict:
    by_type: dict[str, list[dict]] = defaultdict(list)
    for row in mode_rows:
        by_type[row["mutation_type"]].append(row)
    result = {}
    for mutation_type, type_rows in by_type.items():
        positives = [r for r in type_rows if not r["is_negative"]]
        negatives = [r for r in type_rows if r["is_negative"]]
        result[mutation_type] = {
            "recall": _rate([bool(r["hit"]) for r in positives]),
            "false_positive_rate": _rate([bool(r["false_positive"]) for r in negatives]),
            "case_count": len(type_rows),
        }
    return result


def format_comparison_table(summary: dict) -> str:
    lines = ["| metric | full | diff_only |", "|---|---|---|"]
    full = summary.get("full", {})
    diff_only = summary.get("diff_only", {})
    def fmt(v: float | None, as_percent: bool) -> str:
        if v is None:
            return "n/a"
        return f"{v:.1%}" if as_percent else f"{v:.2f}"

    for key, label in (
        ("recall", "recall (positive cases)"),
        ("false_positive_rate", "false-positive rate (negative cases)"),
        ("evidence_validity_rate", "evidence-validity rate"),
        ("avg_latency_seconds", "avg latency (s)"),
        ("avg_estimated_tokens", "avg estimated tokens"),
        ("error_count", "errors"),
    ):
        as_percent = key.endswith(("rate", "recall"))
        lines.append(f"| {label} | {fmt(full.get(key), as_percent)} | {fmt(diff_only.get(key), as_percent)} |")
    return "\n".join(lines)


def write_results(rows: list[dict], summary: dict) -> tuple[Path, Path]:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    json_path = RESULTS_DIR / f"{timestamp}.json"
    json_path.write_text(json.dumps({"rows": rows, "summary": summary}, indent=2, default=str))

    md_lines = [
        "# PR-review context-mode ablation results",
        "",
        f"Generated: {timestamp}",
        "",
        format_comparison_table(summary),
        "",
        "## By mutation type (full mode)",
        "",
        "| mutation_type | recall | false_positive_rate | cases |",
        "|---|---|---|---|",
    ]
    for mutation_type, stats in summary.get("full", {}).get("by_mutation_type", {}).items():
        recall = f"{stats['recall']:.1%}" if stats["recall"] is not None else "n/a"
        fpr = f"{stats['false_positive_rate']:.1%}" if stats["false_positive_rate"] is not None else "n/a"
        md_lines.append(f"| {mutation_type} | {recall} | {fpr} | {stats['case_count']} |")

    latest_path = RESULTS_DIR / "latest.md"
    latest_path.write_text("\n".join(md_lines))
    return json_path, latest_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="Path to the (unmutated) repo the cases were generated from")
    parser.add_argument("--cases-dir", required=True)
    parser.add_argument("--cache-dir", default=str(Path(__file__).parent / "llm_cache"))
    args = parser.parse_args()

    settings = get_settings()
    engine = create_engine(settings.DATABASE_URL)
    Base.metadata.create_all(engine)
    db = Session(bind=engine)

    cases = load_cases(Path(args.cases_dir))
    if not cases:
        print(f"no cases found in {args.cases_dir}")
        return

    embeddings = get_embeddings(settings)
    real_chat_model = build_chat_model(settings, timeout=settings.REVIEW_LLM_TIMEOUT_SECONDS)
    cache_dir = Path(args.cache_dir)

    repository = Repository(url=str(Path(args.repo).resolve()), name=Path(args.repo).name, status=RepositoryStatus.PENDING)
    db.add(repository)
    db.commit()
    ingest_repository(db, repository.id, embeddings=embeddings)
    db.refresh(repository)

    rows: list[dict] = []
    try:
        for case in cases:
            for mode in CONTEXT_MODES:
                cached_model = CachingChatModel(real_chat_model, cache_dir, case["case_id"], mode, settings.CHAT_MODEL)
                result, elapsed, error = run_one(db, repository, case, mode, embeddings, cached_model, settings)
                row = evaluate(case, result, mode, elapsed, error)
                rows.append(row)
                print(f"[{mode}] {case['case_id']}: hit={row['hit']} fp={row['false_positive']} ({elapsed:.2f}s)")

        summary = summarize(rows)
        json_path, latest_path = write_results(rows, summary)

        print()
        print(format_comparison_table(summary))
        print()
        print(f"wrote {json_path}")
        print(f"wrote {latest_path}")
    finally:
        db.delete(repository)
        db.commit()


if __name__ == "__main__":
    main()
