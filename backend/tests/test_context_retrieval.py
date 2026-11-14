from app.review.context_retrieval import (
    build_diff_only_context,
    build_naive_context,
    estimate_tokens,
)
from app.review.diff_parser import DiffLine, FileDiff, Hunk
from app.review.map_changes import ChangedSymbol


def make_symbol(
    change_type="modified", new_source="def add(a, b):\n    return a + b",
    new_start=1, new_end=2, old_start=1, old_end=2, indexed_chunk_id="id",
) -> ChangedSymbol:
    return ChangedSymbol(
        file_path="calculator.py", symbol_name="add", old_symbol_name=None, kind="function",
        language="python", change_type=change_type, signature_changed=False, signature_change_details=[],
        old_start_line=old_start, old_end_line=old_end, new_start_line=new_start, new_end_line=new_end,
        indexed_chunk_id=indexed_chunk_id, new_source=new_source,
    )


def test_estimate_tokens_is_positive_and_monotonic():
    assert estimate_tokens("") >= 1
    assert estimate_tokens("short") < estimate_tokens("a much, much longer piece of text than that")


def test_diff_only_context_labels_sequentially():
    symbols = [make_symbol(), make_symbol(new_source="def subtract(a, b):\n    return a - b")]
    context = build_diff_only_context(symbols)
    assert [c["label"] for c in context] == ["C1", "C2"]
    assert all(c["reason"] == "changed:modified" for c in context)
    assert all(c["sources"] == ["diff"] for c in context)


def test_diff_only_context_uses_new_lines_when_available():
    symbol = make_symbol(new_start=10, new_end=12)
    context = build_diff_only_context([symbol])
    assert context[0]["start_line"] == 10
    assert context[0]["end_line"] == 12


def test_diff_only_context_falls_back_to_old_lines_for_removed_symbol():
    symbol = make_symbol(change_type="removed", new_source=None, new_start=None, new_end=None, old_start=5, old_end=6)
    context = build_diff_only_context([symbol])
    assert context[0]["start_line"] == 5
    assert context[0]["end_line"] == 6
    assert "no new source" in context[0]["source"]


def test_diff_only_context_empty_for_no_symbols():
    assert build_diff_only_context([]) == []


def make_file_diff(path="calculator.py", is_binary=False, is_deleted=False, lines=None) -> FileDiff:
    hunk = Hunk(old_start=1, old_lines=0, new_start=1, new_lines=0, section_header="")
    for tag, text in lines or [("context", "def add(a, b):"), ("add", "    return a + b")]:
        hunk.lines.append(DiffLine(tag, text, 1, 1))
    return FileDiff(
        old_path=path, new_path=None if is_deleted else path,
        is_deleted=is_deleted, is_binary=is_binary, hunks=[hunk],
    )


# -- build_naive_context --------------------------------------------------------------


def test_naive_context_uses_full_file_content_when_supplied():
    file_diff = make_file_diff(path="calculator.py")
    context = build_naive_context([file_diff], {"calculator.py": "def add(a, b):\n    return a + b\n"})
    assert len(context) == 1
    assert context[0]["source"] == "def add(a, b):\n    return a + b\n"
    assert context[0]["file_path"] == "calculator.py"
    assert context[0]["reason"] == "naive_file_context"
    assert context[0]["sources"] == ["naive"]


def test_naive_context_falls_back_to_diff_text_when_full_content_missing():
    file_diff = make_file_diff(path="calculator.py")
    context = build_naive_context([file_diff], {})
    assert len(context) == 1
    assert "return a + b" in context[0]["source"]


def test_naive_context_labels_sequentially_per_file():
    diffs = [make_file_diff(path="a.py"), make_file_diff(path="b.py")]
    context = build_naive_context(diffs, {})
    assert [c["label"] for c in context] == ["C1", "C2"]


def test_naive_context_skips_binary_and_deleted_files():
    diffs = [make_file_diff(path="image.png", is_binary=True), make_file_diff(path="removed.py", is_deleted=True)]
    assert build_naive_context(diffs, {}) == []


def test_naive_context_empty_for_no_diffs():
    assert build_naive_context([], {}) == []
