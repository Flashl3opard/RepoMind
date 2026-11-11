from app.parsing.python_parser import PythonParser
from app.review.diff_parser import DiffLine, FileDiff, Hunk
from app.review.map_changes import IndexedChunkRef, map_file_changes

PARSER = PythonParser()


def make_hunk(old_start: int, new_start: int, lines: list[tuple[str, str]]) -> Hunk:
    """lines: list of (tag, text) with tag in 'add' | 'remove' | 'context'."""
    hunk = Hunk(old_start=old_start, old_lines=0, new_start=new_start, new_lines=0, section_header="")
    old_cursor, new_cursor = old_start, new_start
    for tag, text in lines:
        if tag == "add":
            hunk.lines.append(DiffLine("add", text, None, new_cursor))
            new_cursor += 1
        elif tag == "remove":
            hunk.lines.append(DiffLine("remove", text, old_cursor, None))
            old_cursor += 1
        else:
            hunk.lines.append(DiffLine("context", text, old_cursor, new_cursor))
            old_cursor += 1
            new_cursor += 1
    hunk.old_lines = old_cursor - old_start
    hunk.new_lines = new_cursor - new_start
    return hunk


def test_modified_no_signature_change():
    old_add = IndexedChunkRef(
        chunk_id="add-id", symbol_name="add", kind="function", start_line=1, end_line=2,
        source="def add(a, b):\n    return a + b",
    )
    hunk = make_hunk(
        1, 1,
        [
            ("context", "def add(a, b):"),
            ("remove", "    return a + b"),
            ("add", "    result = a + b"),
            ("add", "    return result"),
        ],
    )
    fd = FileDiff(old_path="calculator.py", new_path="calculator.py", hunks=[hunk])

    changed = map_file_changes(fd, PARSER, [old_add])

    assert len(changed) == 1
    cs = changed[0]
    assert cs.symbol_name == "add"
    assert cs.change_type == "modified"
    assert cs.signature_changed is False
    assert cs.new_start_line == 1
    # new_end_line can't be precisely translated here: the old end line (the body's
    # last line) was itself part of the edit, not an untouched context line.


def test_modified_signature_changed_new_param_with_default():
    old_add = IndexedChunkRef(
        chunk_id="add-id", symbol_name="add", kind="function", start_line=1, end_line=2,
        source="def add(a, b):\n    return a + b",
    )
    hunk = make_hunk(
        1, 1,
        [
            ("remove", "def add(a, b):"),
            ("remove", "    return a + b"),
            ("add", "def add(a, b, c=0):"),
            ("add", "    return a + b + c"),
        ],
    )
    fd = FileDiff(old_path="calculator.py", new_path="calculator.py", hunks=[hunk])

    changed = map_file_changes(fd, PARSER, [old_add])

    assert len(changed) == 1
    cs = changed[0]
    assert cs.change_type == "modified"
    assert cs.signature_changed is True
    assert any("count changed from 2 to 3" in d for d in cs.signature_change_details)
    assert any("new parameter 'c' added" in d for d in cs.signature_change_details)


def test_removed_symbol_with_no_replacement():
    old_subtract = IndexedChunkRef(
        chunk_id="sub-id", symbol_name="subtract", kind="function", start_line=4, end_line=5,
        source="def subtract(a, b):\n    return a - b",
    )
    hunk = make_hunk(4, 4, [("remove", "def subtract(a, b):"), ("remove", "    return a - b")])
    fd = FileDiff(old_path="calculator.py", new_path="calculator.py", hunks=[hunk])

    changed = map_file_changes(fd, PARSER, [old_subtract])

    assert len(changed) == 1
    assert changed[0].change_type == "removed"
    assert changed[0].symbol_name == "subtract"
    assert changed[0].indexed_chunk_id == "sub-id"


def test_added_symbol_new_function_inserted():
    old_add = IndexedChunkRef(
        chunk_id="add-id", symbol_name="add", kind="function", start_line=1, end_line=2,
        source="def add(a, b):\n    return a + b",
    )
    old_subtract = IndexedChunkRef(
        chunk_id="sub-id", symbol_name="subtract", kind="function", start_line=4, end_line=5,
        source="def subtract(a, b):\n    return a - b",
    )
    # pure insertion after line 5/6, doesn't overlap either existing chunk
    hunk = make_hunk(7, 7, [("add", "def multiply(a, b):"), ("add", "    return a * b")])
    fd = FileDiff(old_path="calculator.py", new_path="calculator.py", hunks=[hunk])

    changed = map_file_changes(fd, PARSER, [old_add, old_subtract])

    assert len(changed) == 1
    cs = changed[0]
    assert cs.change_type == "added"
    assert cs.symbol_name == "multiply"
    assert cs.new_start_line == 7
    assert cs.indexed_chunk_id is None


def test_untouched_symbol_is_excluded():
    old_add = IndexedChunkRef(
        chunk_id="add-id", symbol_name="add", kind="function", start_line=1, end_line=2,
        source="def add(a, b):\n    return a + b",
    )
    old_subtract = IndexedChunkRef(
        chunk_id="sub-id", symbol_name="subtract", kind="function", start_line=4, end_line=5,
        source="def subtract(a, b):\n    return a - b",
    )
    hunk = make_hunk(4, 4, [("remove", "def subtract(a, b):"), ("remove", "    return a - b")])
    fd = FileDiff(old_path="calculator.py", new_path="calculator.py", hunks=[hunk])

    changed = map_file_changes(fd, PARSER, [old_add, old_subtract])

    assert len(changed) == 1
    assert changed[0].symbol_name == "subtract"  # "add" never touched, not reported


def test_renamed_symbol_with_similar_body_is_detected():
    old_add = IndexedChunkRef(
        chunk_id="add-id", symbol_name="add", kind="function", start_line=1, end_line=2,
        source="def add(a, b):\n    return a + b",
    )
    hunk = make_hunk(
        1, 1,
        [
            ("remove", "def add(a, b):"),
            ("remove", "    return a + b"),
            ("add", "def plus(a, b):"),
            ("add", "    return a + b"),
        ],
    )
    fd = FileDiff(old_path="calculator.py", new_path="calculator.py", hunks=[hunk])

    changed = map_file_changes(fd, PARSER, [old_add])

    assert len(changed) == 1
    cs = changed[0]
    assert cs.change_type == "renamed"
    assert cs.old_symbol_name == "add"
    assert cs.symbol_name == "plus"


def test_removed_symbol_not_paired_with_dissimilar_added_symbol():
    old_add = IndexedChunkRef(
        chunk_id="add-id", symbol_name="add", kind="function", start_line=1, end_line=2,
        source="def add(a, b):\n    return a + b",
    )
    hunk = make_hunk(
        1, 1,
        [
            ("remove", "def add(a, b):"),
            ("remove", "    return a + b"),
            ("add", "def totally_unrelated(x, y, z):"),
            ("add", "    return (x * y) ** z - validate_everything(x, y, z)"),
        ],
    )
    fd = FileDiff(old_path="calculator.py", new_path="calculator.py", hunks=[hunk])

    changed = map_file_changes(fd, PARSER, [old_add])

    change_types = {c.symbol_name: c.change_type for c in changed}
    assert change_types["add"] == "removed"
    assert change_types["totally_unrelated"] == "added"


def test_new_file_all_symbols_are_added():
    hunk = make_hunk(1, 1, [("add", "def greet(name):"), ("add", "    return f'hi {name}'")])
    fd = FileDiff(old_path=None, new_path="greetings.py", is_new=True, hunks=[hunk])

    changed = map_file_changes(fd, PARSER, [])

    assert len(changed) == 1
    assert changed[0].change_type == "added"
    assert changed[0].symbol_name == "greet"


def test_deleted_file_all_symbols_are_removed():
    old_fn = IndexedChunkRef(
        chunk_id="legacy-id", symbol_name="old_function", kind="function", start_line=1, end_line=2,
        source="def old_function():\n    pass",
    )
    hunk = make_hunk(1, 1, [("remove", "def old_function():"), ("remove", "    pass")])
    fd = FileDiff(old_path="legacy.py", new_path=None, is_deleted=True, hunks=[hunk])

    changed = map_file_changes(fd, PARSER, [old_fn])

    assert len(changed) == 1
    assert changed[0].change_type == "removed"
    assert changed[0].file_path == "legacy.py"


def test_binary_file_returns_no_changes():
    fd = FileDiff(old_path="image.png", new_path="image.png", is_binary=True, hunks=[])
    changed = map_file_changes(fd, PARSER, [])
    assert changed == []


def test_body_only_edit_whose_hunk_excludes_the_def_line_is_modified_not_removed():
    # Regression: a hunk deep in a function's body (default diff context doesn't reach
    # back to "def main():") must not be mistaken for a removal just because the
    # symbol's name doesn't appear in that one hunk's own parsed fragment.
    old_main = IndexedChunkRef(
        chunk_id="main-id", symbol_name="main", kind="function", start_line=5, end_line=10,
        source=(
            "def main():\n"
            "    total = add(1, 2)\n"
            "    total = subtract(total, 1)\n"
            "    total = multiply(total, 4)\n"
            "    total = divide(total, 2)\n"
            "    return format_result(total)"
        ),
    )
    # only line 8 changes; the "def main():" line (5) never appears in this hunk at all
    hunk = make_hunk(8, 8, [("remove", "    total = multiply(total, 4)"), ("add", "    total = product(total, 4)")])
    fd = FileDiff(old_path="main.py", new_path="main.py", hunks=[hunk])

    changed = map_file_changes(fd, PARSER, [old_main])

    assert len(changed) == 1
    assert changed[0].symbol_name == "main"
    assert changed[0].change_type == "modified"
    assert changed[0].signature_changed is False


def test_body_only_edit_translates_new_line_numbers_via_def_line_context():
    old_add = IndexedChunkRef(
        chunk_id="add-id", symbol_name="add", kind="function", start_line=10, end_line=12,
        source="def add(a, b):\n    result = a + b\n    return result",
    )
    # an earlier insertion shifts everything after it by +2; the def line (old 10)
    # appears as context so its new position can be translated exactly.
    hunk = make_hunk(
        10, 10,
        [
            ("add", "# new comment line one"),
            ("add", "# new comment line two"),
            ("context", "def add(a, b):"),
            ("context", "    result = a + b"),
            ("remove", "    return result"),
            ("add", "    return result  # unchanged behavior"),
        ],
    )
    fd = FileDiff(old_path="calculator.py", new_path="calculator.py", hunks=[hunk])

    changed = map_file_changes(fd, PARSER, [old_add])

    assert len(changed) == 1
    cs = changed[0]
    assert cs.change_type == "modified"
    assert cs.new_start_line == 12  # old line 10 shifted by +2


def test_no_parser_returns_no_changes():
    hunk = make_hunk(1, 1, [("add", "fn main() {}")])
    fd = FileDiff(old_path="main.rs", new_path="main.rs", hunks=[hunk])
    changed = map_file_changes(fd, None, [])
    assert changed == []
