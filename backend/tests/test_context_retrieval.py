from app.review.context_retrieval import build_diff_only_context, estimate_tokens
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
