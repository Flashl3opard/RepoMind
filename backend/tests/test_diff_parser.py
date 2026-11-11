from app.review.diff_parser import (
    line_in_any_range,
    new_side_ranges_by_file,
    old_side_ranges_by_file,
    parse_diff,
    range_overlaps_any,
)

SIMPLE_MODIFY = """\
diff --git a/calculator.py b/calculator.py
index abc123..def456 100644
--- a/calculator.py
+++ b/calculator.py
@@ -1,5 +1,6 @@
 def add(a, b):
-    return a + b
+    result = a + b
+    return result


 def subtract(a, b):
"""

NEW_FILE = """\
diff --git a/utils.py b/utils.py
new file mode 100644
index 0000000..1111111
--- /dev/null
+++ b/utils.py
@@ -0,0 +1,2 @@
+def format_result(value):
+    return f"Result: {value}"
"""

DELETED_FILE = """\
diff --git a/legacy.py b/legacy.py
deleted file mode 100644
index 2222222..0000000
--- a/legacy.py
+++ /dev/null
@@ -1,2 +0,0 @@
-def old_function():
-    pass
"""

PURE_RENAME_NO_CONTENT_CHANGE = """\
diff --git a/old_name.py b/new_name.py
similarity index 100%
rename from old_name.py
rename to new_name.py
"""

RENAME_WITH_MODIFY = """\
diff --git a/old_name.py b/new_name.py
similarity index 90%
rename from old_name.py
rename to new_name.py
index abc123..def456 100644
--- a/old_name.py
+++ b/new_name.py
@@ -1,3 +1,3 @@
 def foo():
-    return 1
+    return 2
"""

BINARY_FILE = """\
diff --git a/image.png b/image.png
index abc123..def456 100644
Binary files a/image.png and b/image.png differ
"""

TWO_FILES = SIMPLE_MODIFY + NEW_FILE

NO_NEWLINE_MARKER = """\
diff --git a/foo.py b/foo.py
index abc123..def456 100644
--- a/foo.py
+++ b/foo.py
@@ -1,1 +1,1 @@
-x = 1
\\ No newline at end of file
+x = 2
\\ No newline at end of file
"""


def test_simple_modify_has_one_file_and_one_hunk():
    diffs = parse_diff(SIMPLE_MODIFY)
    assert len(diffs) == 1
    fd = diffs[0]
    assert fd.old_path == "calculator.py"
    assert fd.new_path == "calculator.py"
    assert fd.path == "calculator.py"
    assert not fd.is_new
    assert not fd.is_deleted
    assert not fd.is_renamed
    assert not fd.is_binary
    assert len(fd.hunks) == 1


def test_simple_modify_line_numbers_are_correct():
    hunk = parse_diff(SIMPLE_MODIFY)[0].hunks[0]
    assert hunk.old_start == 1
    assert hunk.new_start == 1
    assert hunk.removed_line_numbers == [2]
    assert hunk.added_line_numbers == [2, 3]
    # context lines keep both old and new numbers
    context_lines = [line for line in hunk.lines if line.tag == "context"]
    assert all(line.old_line_no is not None and line.new_line_no is not None for line in context_lines)


def test_new_file_has_all_added_lines_from_line_one():
    fd = parse_diff(NEW_FILE)[0]
    assert fd.is_new
    assert fd.old_path is None
    assert fd.new_path == "utils.py"
    assert fd.path == "utils.py"
    hunk = fd.hunks[0]
    assert hunk.added_line_numbers == [1, 2]
    assert hunk.removed_line_numbers == []
    assert "def format_result(value):" in hunk.new_text()


def test_deleted_file_has_all_removed_lines_and_no_new_path():
    fd = parse_diff(DELETED_FILE)[0]
    assert fd.is_deleted
    assert fd.new_path is None
    assert fd.old_path == "legacy.py"
    assert fd.path == "legacy.py"
    hunk = fd.hunks[0]
    assert hunk.removed_line_numbers == [1, 2]
    assert hunk.added_line_numbers == []


def test_pure_rename_with_no_content_change_has_no_hunks():
    fd = parse_diff(PURE_RENAME_NO_CONTENT_CHANGE)[0]
    assert fd.is_renamed
    assert fd.old_path == "old_name.py"
    assert fd.new_path == "new_name.py"
    assert fd.hunks == []


def test_rename_with_modify_has_both_rename_and_hunk():
    fd = parse_diff(RENAME_WITH_MODIFY)[0]
    assert fd.is_renamed
    assert fd.old_path == "old_name.py"
    assert fd.new_path == "new_name.py"
    assert len(fd.hunks) == 1
    assert fd.hunks[0].removed_line_numbers == [2]
    assert fd.hunks[0].added_line_numbers == [2]


def test_binary_file_is_skipped_with_no_hunks():
    fd = parse_diff(BINARY_FILE)[0]
    assert fd.is_binary
    assert fd.hunks == []
    assert fd.path == "image.png"


def test_multiple_files_in_one_diff():
    diffs = parse_diff(TWO_FILES)
    assert len(diffs) == 2
    assert diffs[0].path == "calculator.py"
    assert diffs[1].path == "utils.py"
    assert diffs[1].is_new


def test_no_newline_marker_is_ignored_not_treated_as_content():
    fd = parse_diff(NO_NEWLINE_MARKER)[0]
    hunk = fd.hunks[0]
    texts = [line.text for line in hunk.lines]
    assert "\\ No newline at end of file" not in texts
    assert hunk.removed_line_numbers == [1]
    assert hunk.added_line_numbers == [1]


def test_hunk_new_text_excludes_removed_lines():
    hunk = parse_diff(SIMPLE_MODIFY)[0].hunks[0]
    new_text = hunk.new_text()
    assert "result = a + b" in new_text
    assert "return a + b" not in new_text  # that line was removed, not present on new side


def test_hunk_old_text_excludes_added_lines():
    hunk = parse_diff(SIMPLE_MODIFY)[0].hunks[0]
    old_text = hunk.old_text()
    assert "return a + b" in old_text
    assert "result = a + b" not in old_text


def test_empty_diff_returns_empty_list():
    assert parse_diff("") == []


def test_old_and_new_range_properties():
    hunk = parse_diff(SIMPLE_MODIFY)[0].hunks[0]
    assert hunk.old_range == (1, 5)
    assert hunk.new_range == (1, 6)


def test_old_side_ranges_by_file_uses_lookup_path():
    diffs = parse_diff(RENAME_WITH_MODIFY)
    ranges = old_side_ranges_by_file(diffs)
    assert "old_name.py" in ranges
    assert "new_name.py" not in ranges


def test_new_side_ranges_by_file_uses_current_path():
    diffs = parse_diff(RENAME_WITH_MODIFY)
    ranges = new_side_ranges_by_file(diffs)
    assert "new_name.py" in ranges
    assert "old_name.py" not in ranges


def test_old_side_ranges_empty_for_pure_rename_with_no_hunks():
    diffs = parse_diff(PURE_RENAME_NO_CONTENT_CHANGE)
    assert old_side_ranges_by_file(diffs) == {}


def test_line_in_any_range():
    assert line_in_any_range(5, [(1, 3), (4, 10)])
    assert not line_in_any_range(20, [(1, 3), (4, 10)])


def test_range_overlaps_any():
    assert range_overlaps_any(5, 8, [(1, 3), (6, 10)])
    assert not range_overlaps_any(20, 25, [(1, 3), (6, 10)])
