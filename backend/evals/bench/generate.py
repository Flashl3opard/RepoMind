"""Mutation-based benchmark generator for the PR-review context-mode ablation.

Picks functions with at least 2 callers in other files (using the same Tree-sitter
parsing and call extraction the real ingestion pipeline uses -- see
app/parsing/python_parser.py) and creates small, realistic PR diffs that mutate ONLY
the callee's file: breaking changes (positive cases, with ground-truth
expected_caller_files from the real call graph) and safe changes (negative cases,
which must NOT trigger a breaking_change finding). Deterministic given --seed; never
modifies the source repo (works on a temp copy). Python only, and only functions with
a single-line, non-decorated, top-level signature (see mutations.py).

Usage:
    uv run python -m evals.bench.generate --repo /path/to/repo --seed 0 --max-cases 20
"""

import argparse
import difflib
import random
import shutil
import sys
import tempfile
import uuid
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.parsing.base import ParsedChunk  # noqa: E402
from app.parsing.python_parser import PythonParser  # noqa: E402
from evals.bench.mutations import (  # noqa: E402
    add_docstring,
    add_optional_param,
    add_required_param,
    change_return_shape,
    rename_function,
    rename_local_variable,
)

PARSER = PythonParser()

POSITIVE_MUTATIONS = ("add_required_param", "remove_function", "rename_function", "change_return_shape")
NEGATIVE_MUTATIONS = ("add_optional_param", "add_docstring", "rename_local_variable")


@dataclass(slots=True)
class Candidate:
    file_path: str
    symbol_name: str
    start_line: int
    end_line: int
    source: str
    caller_files: list[str]


def _is_simple_candidate(chunk: ParsedChunk) -> bool:
    if chunk.kind != "function" or chunk.parent_symbol is not None:
        return False
    first_line = chunk.source.splitlines()[0] if chunk.source else ""
    return first_line.rstrip().endswith(":") and first_line.lstrip().startswith("def ")


def find_candidates(repo_path: Path) -> list[Candidate]:
    """Functions with >=2 callers in files other than their own, using the exact
    same parser/call-extraction the real ingestion pipeline uses."""
    chunks_by_file: dict[str, list[ParsedChunk]] = {}
    for py_file in sorted(repo_path.rglob("*.py")):
        if ".git" in py_file.parts:
            continue
        rel = py_file.relative_to(repo_path).as_posix()
        try:
            source = py_file.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        chunks_by_file[rel] = PARSER.parse(source, rel)

    caller_files_by_name: dict[str, set[str]] = defaultdict(set)
    for file_path, chunks in chunks_by_file.items():
        for chunk in chunks:
            for call in chunk.calls:
                simple_name = call.rsplit(".", 1)[-1]
                caller_files_by_name[simple_name].add(file_path)

    candidates: list[Candidate] = []
    for file_path, chunks in chunks_by_file.items():
        for chunk in chunks:
            if not _is_simple_candidate(chunk):
                continue
            caller_files = sorted(f for f in caller_files_by_name.get(chunk.symbol_name, set()) if f != file_path)
            if len(caller_files) >= 2:
                candidates.append(
                    Candidate(file_path, chunk.symbol_name, chunk.start_line, chunk.end_line, chunk.source, caller_files)
                )
    return candidates


def _make_unified_diff(file_path: str, old_text: str, new_text: str) -> str:
    old_lines = old_text.splitlines(keepends=True)
    new_lines = new_text.splitlines(keepends=True)
    diff_lines = list(difflib.unified_diff(old_lines, new_lines, fromfile=f"a/{file_path}", tofile=f"b/{file_path}"))
    if not diff_lines:
        return ""
    body = "".join(diff_lines)
    if not body.endswith("\n"):
        body += "\n"
    return f"diff --git a/{file_path} b/{file_path}\n{body}"


def _apply_mutation(old_text: str, candidate: Candidate, mutation_type: str) -> str | None:
    lines = old_text.splitlines(keepends=True)
    before = "".join(lines[: candidate.start_line - 1])
    after = "".join(lines[candidate.end_line :])

    if mutation_type == "remove_function":
        return before + after

    if mutation_type == "add_required_param":
        mutated = add_required_param(candidate.source)
    elif mutation_type == "rename_function":
        mutated = rename_function(candidate.source, f"{candidate.symbol_name}_v2")
    elif mutation_type == "change_return_shape":
        mutated = change_return_shape(candidate.source)
    elif mutation_type == "add_optional_param":
        mutated = add_optional_param(candidate.source)
    elif mutation_type == "add_docstring":
        mutated = add_docstring(candidate.source)
    elif mutation_type == "rename_local_variable":
        mutated = rename_local_variable(candidate.source)
    else:
        raise ValueError(f"unknown mutation type: {mutation_type}")

    if mutated is None:
        return None
    if not mutated.endswith("\n") and after:
        mutated += "\n"
    return before + mutated + after


def generate_cases(repo_path: Path, seed: int, max_cases: int) -> list[dict]:
    rng = random.Random(seed)
    candidates = find_candidates(repo_path)
    rng.shuffle(candidates)

    cases: list[dict] = []
    for candidate in candidates:
        if len(cases) >= max_cases:
            break
        old_text = (repo_path / candidate.file_path).read_text(encoding="utf-8")

        mutation_types = list(POSITIVE_MUTATIONS) + list(NEGATIVE_MUTATIONS)
        rng.shuffle(mutation_types)
        for mutation_type in mutation_types:
            if len(cases) >= max_cases:
                break
            new_text = _apply_mutation(old_text, candidate, mutation_type)
            if new_text is None or new_text == old_text:
                continue
            diff_text = _make_unified_diff(candidate.file_path, old_text, new_text)
            if not diff_text:
                continue
            is_negative = mutation_type in NEGATIVE_MUTATIONS
            cases.append(
                {
                    "case_id": f"{len(cases):03d}_{mutation_type}_{candidate.symbol_name}",
                    "diff": diff_text,
                    "expected": {
                        "mutation_type": mutation_type,
                        "changed_symbol": candidate.symbol_name,
                        "changed_file": candidate.file_path,
                        "expected_caller_files": candidate.caller_files,
                        "is_negative": is_negative,
                    },
                }
            )
    return cases


def write_cases(cases: list[dict], out_dir: Path, repo_name: str) -> None:
    repo_dir = out_dir / repo_name
    repo_dir.mkdir(parents=True, exist_ok=True)
    for case in cases:
        case_dir = repo_dir / case["case_id"]
        case_dir.mkdir(parents=True, exist_ok=True)
        (case_dir / "pr.diff").write_text(case["diff"], encoding="utf-8")
        (case_dir / "expected.yaml").write_text(yaml.safe_dump(case["expected"], sort_keys=False), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="Path to a local git repo (Python), already ingested at HEAD")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--max-cases", type=int, default=20)
    parser.add_argument("--out", default=str(Path(__file__).parent / "cases"))
    args = parser.parse_args()

    source_repo = Path(args.repo).resolve()
    repo_name = source_repo.name

    with tempfile.TemporaryDirectory(prefix=f"bench-{uuid.uuid4().hex[:8]}-") as tmp:
        work_copy = Path(tmp) / repo_name
        shutil.copytree(source_repo, work_copy, ignore=shutil.ignore_patterns(".git"))

        cases = generate_cases(work_copy, args.seed, args.max_cases)
        write_cases(cases, Path(args.out), repo_name)

    positives = sum(1 for c in cases if not c["expected"]["is_negative"])
    negatives = len(cases) - positives
    print(f"generated {len(cases)} cases ({positives} positive, {negatives} negative) for {repo_name}")
    print(f"written to {Path(args.out) / repo_name}")


if __name__ == "__main__":
    main()
