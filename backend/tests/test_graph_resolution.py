import uuid

from app.retrieval.graph import CandidateMatch, select_preferred_targets

SOURCE_FILE = uuid.uuid4()
OTHER_FILE_A = uuid.uuid4()
OTHER_FILE_B = uuid.uuid4()


def _candidate(file_id: uuid.UUID, file_path: str) -> CandidateMatch:
    return CandidateMatch(chunk_id=uuid.uuid4(), file_id=file_id, file_path=file_path)


def test_no_candidates_returns_empty_and_never_raises():
    assert select_preferred_targets(SOURCE_FILE, set(), []) == []


def test_single_candidate_in_same_file_is_not_ambiguous():
    candidate = _candidate(SOURCE_FILE, "app/main.py")
    resolved = select_preferred_targets(SOURCE_FILE, set(), [candidate])
    assert len(resolved) == 1
    assert resolved[0].chunk_id == candidate.chunk_id
    assert resolved[0].ambiguous is False


def test_imported_file_is_preferred_over_same_file():
    same_file_candidate = _candidate(SOURCE_FILE, "app/main.py")
    imported_candidate = _candidate(OTHER_FILE_A, "app/services/helper.py")
    resolved = select_preferred_targets(
        SOURCE_FILE, {"app.services.helper"}, [same_file_candidate, imported_candidate]
    )
    assert len(resolved) == 1
    assert resolved[0].chunk_id == imported_candidate.chunk_id
    assert resolved[0].ambiguous is False


def test_same_file_is_preferred_over_unrelated_file():
    same_file_candidate = _candidate(SOURCE_FILE, "app/main.py")
    unrelated_candidate = _candidate(OTHER_FILE_A, "app/unrelated.py")
    resolved = select_preferred_targets(SOURCE_FILE, set(), [same_file_candidate, unrelated_candidate])
    assert len(resolved) == 1
    assert resolved[0].chunk_id == same_file_candidate.chunk_id


def test_multiple_candidates_in_winning_tier_are_capped_and_marked_ambiguous():
    a = _candidate(OTHER_FILE_A, "pkg/a.py")
    b = _candidate(OTHER_FILE_B, "pkg/b.py")
    c = _candidate(uuid.uuid4(), "pkg/c.py")
    resolved = select_preferred_targets(SOURCE_FILE, set(), [a, b, c])
    assert len(resolved) == 2  # capped at MAX_AMBIGUOUS_CANDIDATES
    assert all(r.ambiguous for r in resolved)
    assert {r.chunk_id for r in resolved} <= {a.chunk_id, b.chunk_id, c.chunk_id}


def test_unrelated_candidates_dont_block_a_clear_imported_match():
    imported = _candidate(OTHER_FILE_A, "pkg/target.py")
    unrelated_one = _candidate(uuid.uuid4(), "pkg/other1.py")
    unrelated_two = _candidate(uuid.uuid4(), "pkg/other2.py")
    resolved = select_preferred_targets(
        SOURCE_FILE, {"pkg.target"}, [unrelated_one, imported, unrelated_two]
    )
    assert len(resolved) == 1
    assert resolved[0].ambiguous is False
    assert resolved[0].chunk_id == imported.chunk_id
