"""Pure unified-diff parser. No I/O, no DB -- takes diff text, returns structured data."""

import re
from collections import defaultdict
from dataclasses import dataclass, field

_DIFF_GIT_RE = re.compile(r"^diff --git a/(.+) b/(.+)$")
_HUNK_HEADER_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$")
_OLD_PATH_RE = re.compile(r"^--- (?:a/(.+)|(/dev/null))$")
_NEW_PATH_RE = re.compile(r"^\+\+\+ (?:b/(.+)|(/dev/null))$")


@dataclass(slots=True)
class DiffLine:
    tag: str  # "add" | "remove" | "context"
    text: str
    old_line_no: int | None
    new_line_no: int | None


@dataclass(slots=True)
class Hunk:
    old_start: int
    old_lines: int
    new_start: int
    new_lines: int
    section_header: str  # trailing text on the "@@ ... @@" line, often the enclosing def
    lines: list[DiffLine] = field(default_factory=list)

    @property
    def added_line_numbers(self) -> list[int]:
        return [line.new_line_no for line in self.lines if line.tag == "add" and line.new_line_no is not None]

    @property
    def removed_line_numbers(self) -> list[int]:
        return [line.old_line_no for line in self.lines if line.tag == "remove" and line.old_line_no is not None]

    @property
    def old_range(self) -> tuple[int, int]:
        return self.old_start, self.old_start + max(self.old_lines, 1) - 1

    @property
    def new_range(self) -> tuple[int, int]:
        return self.new_start, self.new_start + max(self.new_lines, 1) - 1

    def new_text(self) -> str:
        """Context + added lines, in order -- i.e. what this hunk's span looks like
        on the new side. Does not include surrounding file content outside the hunk."""
        return "\n".join(line.text for line in self.lines if line.tag in ("add", "context"))

    def old_text(self) -> str:
        """Context + removed lines, in order -- the hunk's span on the old side."""
        return "\n".join(line.text for line in self.lines if line.tag in ("remove", "context"))


@dataclass(slots=True)
class FileDiff:
    old_path: str | None  # None for a new file
    new_path: str | None  # None for a deleted file
    is_new: bool = False
    is_deleted: bool = False
    is_renamed: bool = False
    is_binary: bool = False
    hunks: list[Hunk] = field(default_factory=list)

    @property
    def path(self) -> str:
        """The file's current path: new_path, falling back to old_path for deletions."""
        return self.new_path or self.old_path or ""

    @property
    def lookup_path(self) -> str:
        """The path the base-branch index would have this file under: old_path when
        known (covers renames, where the index still has it filed under the old name),
        falling back to new_path for files that are new in this PR."""
        return self.old_path or self.new_path or ""


def parse_diff(diff_text: str) -> list[FileDiff]:
    """Parse unified diff text (as produced by `git diff`/a GitHub PR diff) into
    structured FileDiffs. Handles renames, new files, deleted files, and binary files
    (recorded with is_binary=True and no hunks, never raises on them)."""
    lines = diff_text.splitlines()
    file_diffs: list[FileDiff] = []

    i = 0
    n = len(lines)
    while i < n:
        match = _DIFF_GIT_RE.match(lines[i])
        if not match:
            i += 1
            continue

        header_old_path, header_new_path = match.group(1), match.group(2)
        i += 1

        file_diff = FileDiff(old_path=header_old_path, new_path=header_new_path)
        old_path_from_marker: str | None = None
        new_path_from_marker: str | None = None

        # Consume this file's header lines until the next hunk or the next file block.
        while i < n and not lines[i].startswith("@@") and not _DIFF_GIT_RE.match(lines[i]):
            line = lines[i]
            if line.startswith("new file mode"):
                file_diff.is_new = True
            elif line.startswith("deleted file mode"):
                file_diff.is_deleted = True
            elif line.startswith("rename from "):
                file_diff.is_renamed = True
                old_path_from_marker = line.removeprefix("rename from ")
            elif line.startswith("rename to "):
                file_diff.is_renamed = True
                new_path_from_marker = line.removeprefix("rename to ")
            elif line.startswith("Binary files ") and line.endswith(" differ"):
                file_diff.is_binary = True
            elif (m := _OLD_PATH_RE.match(line)) is not None:
                old_path_from_marker = m.group(1)  # None (dev/null) handled below
                if m.group(2):
                    file_diff.is_new = True
            elif (m := _NEW_PATH_RE.match(line)) is not None:
                new_path_from_marker = m.group(1)
                if m.group(2):
                    file_diff.is_deleted = True
            i += 1

        if old_path_from_marker is not None:
            file_diff.old_path = old_path_from_marker
        if new_path_from_marker is not None:
            file_diff.new_path = new_path_from_marker
        if file_diff.is_new:
            file_diff.old_path = None
        if file_diff.is_deleted:
            file_diff.new_path = None

        # Hunks (skipped entirely for binary files -- there's nothing textual to show).
        while i < n and lines[i].startswith("@@"):
            hunk_match = _HUNK_HEADER_RE.match(lines[i])
            if hunk_match is None:
                i += 1
                continue
            old_start = int(hunk_match.group(1))
            old_count = int(hunk_match.group(2)) if hunk_match.group(2) is not None else 1
            new_start = int(hunk_match.group(3))
            new_count = int(hunk_match.group(4)) if hunk_match.group(4) is not None else 1
            hunk = Hunk(
                old_start=old_start,
                old_lines=old_count,
                new_start=new_start,
                new_lines=new_count,
                section_header=hunk_match.group(5).strip(),
            )
            i += 1

            old_cursor = old_start
            new_cursor = new_start
            while i < n and not lines[i].startswith("@@") and not _DIFF_GIT_RE.match(lines[i]):
                raw = lines[i]
                if raw.startswith("\\"):  # "\ No newline at end of file"
                    i += 1
                    continue
                if raw.startswith("+"):
                    hunk.lines.append(DiffLine("add", raw[1:], None, new_cursor))
                    new_cursor += 1
                elif raw.startswith("-"):
                    hunk.lines.append(DiffLine("remove", raw[1:], old_cursor, None))
                    old_cursor += 1
                else:
                    text = raw[1:] if raw.startswith(" ") else raw
                    hunk.lines.append(DiffLine("context", text, old_cursor, new_cursor))
                    old_cursor += 1
                    new_cursor += 1
                i += 1
            file_diff.hunks.append(hunk)

        file_diffs.append(file_diff)

    return file_diffs


def old_side_ranges_by_file(file_diffs: list[FileDiff]) -> dict[str, list[tuple[int, int]]]:
    """{file's base-branch path: [(old_start, old_end), ...]} across every hunk,
    keyed by `lookup_path` so a rename still maps to where the index has the file."""
    result: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for file_diff in file_diffs:
        for hunk in file_diff.hunks:
            result[file_diff.lookup_path].append(hunk.old_range)
    return dict(result)


def new_side_ranges_by_file(file_diffs: list[FileDiff]) -> dict[str, list[tuple[int, int]]]:
    """{file's current (PR head) path: [(new_start, new_end), ...]} across every hunk."""
    result: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for file_diff in file_diffs:
        for hunk in file_diff.hunks:
            result[file_diff.path].append(hunk.new_range)
    return dict(result)


def line_in_any_range(line: int, ranges: list[tuple[int, int]]) -> bool:
    return any(start <= line <= end for start, end in ranges)


def range_overlaps_any(start: int, end: int, ranges: list[tuple[int, int]]) -> bool:
    return any(max(start, r_start) <= min(end, r_end) for r_start, r_end in ranges)
