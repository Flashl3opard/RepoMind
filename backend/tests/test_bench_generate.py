import ast

from app.review.diff_parser import parse_diff
from evals.bench.generate import find_candidates, generate_cases

CALCULATOR = (
    "def add(a, b):\n"
    "    return a + b\n"
    "\n\n"
    "def subtract(a, b):\n"
    "    return a - b\n"
)
MAIN = (
    "from calculator import add, subtract\n"
    "\n\n"
    "def main():\n"
    "    total = add(1, 2)\n"
    "    return subtract(total, 1)\n"
)
TEST_CALCULATOR = (
    "from calculator import add, subtract\n"
    "\n\n"
    "def test_add():\n"
    "    assert add(1, 2) == 3\n"
    "\n\n"
    "def test_subtract():\n"
    "    assert subtract(5, 2) == 3\n"
)


def write_repo(tmp_path):
    (tmp_path / "calculator.py").write_text(CALCULATOR)
    (tmp_path / "main.py").write_text(MAIN)
    (tmp_path / "test_calculator.py").write_text(TEST_CALCULATOR)
    return tmp_path


def test_find_candidates_requires_two_caller_files(tmp_path):
    repo = write_repo(tmp_path)
    candidates = find_candidates(repo)
    names = {c.symbol_name for c in candidates}
    assert names == {"add", "subtract"}
    for c in candidates:
        assert set(c.caller_files) == {"main.py", "test_calculator.py"}


def test_find_candidates_excludes_functions_with_one_caller_file(tmp_path):
    repo = tmp_path
    (repo / "lonely.py").write_text("def only_called_once():\n    return 1\n")
    (repo / "caller.py").write_text("from lonely import only_called_once\n\n\ndef use():\n    return only_called_once()\n")
    candidates = find_candidates(repo)
    assert "only_called_once" not in {c.symbol_name for c in candidates}


def test_generate_cases_is_deterministic_given_same_seed(tmp_path):
    repo = write_repo(tmp_path)
    cases_a = generate_cases(repo, seed=42, max_cases=10)
    cases_b = generate_cases(repo, seed=42, max_cases=10)
    assert [c["case_id"] for c in cases_a] == [c["case_id"] for c in cases_b]
    assert [c["diff"] for c in cases_a] == [c["diff"] for c in cases_b]


def test_generate_cases_different_seeds_can_differ(tmp_path):
    repo = write_repo(tmp_path)
    cases_a = generate_cases(repo, seed=1, max_cases=3)
    cases_b = generate_cases(repo, seed=2, max_cases=3)
    # not a strict guarantee for all seeds, but true for these two with this fixture
    assert cases_a != cases_b


def test_generate_cases_respects_max_cases(tmp_path):
    repo = write_repo(tmp_path)
    cases = generate_cases(repo, seed=0, max_cases=3)
    assert len(cases) <= 3


def test_generate_cases_never_modifies_the_source_repo(tmp_path):
    repo = write_repo(tmp_path)
    original = (repo / "calculator.py").read_text()
    generate_cases(repo, seed=0, max_cases=20)
    assert (repo / "calculator.py").read_text() == original


def test_generate_cases_every_diff_is_parseable_and_mutated_file_is_valid_python(tmp_path):
    repo = write_repo(tmp_path)
    cases = generate_cases(repo, seed=0, max_cases=20)
    assert len(cases) > 0

    for case in cases:
        file_diffs = parse_diff(case["diff"])
        assert len(file_diffs) == 1
        fd = file_diffs[0]
        assert not fd.is_binary
        assert len(fd.hunks) == 1  # each mutation touches exactly one contiguous span

        old_lines = (repo / fd.path).read_text().splitlines()
        hunk = fd.hunks[0]
        before = old_lines[: hunk.old_start - 1]
        after = old_lines[hunk.old_start - 1 + hunk.old_lines :]
        new_middle = hunk.new_text().splitlines() if hunk.new_text() else []
        ast.parse("\n".join(before + new_middle + after))


def test_generate_cases_positive_and_negative_both_present(tmp_path):
    repo = write_repo(tmp_path)
    cases = generate_cases(repo, seed=0, max_cases=20)
    is_negative = {c["expected"]["is_negative"] for c in cases}
    assert True in is_negative
    assert False in is_negative


def test_generate_cases_expected_caller_files_match_ground_truth(tmp_path):
    repo = write_repo(tmp_path)
    cases = generate_cases(repo, seed=0, max_cases=20)
    for case in cases:
        assert set(case["expected"]["expected_caller_files"]) == {"main.py", "test_calculator.py"}
