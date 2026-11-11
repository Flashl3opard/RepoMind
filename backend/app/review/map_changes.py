"""Map a diff's changed line ranges to symbols.

Pure core (`map_file_changes`) takes a parsed FileDiff plus the base-branch index's
chunks for that file and figures out, per symbol, whether it was added/modified/
removed/renamed, and -- deterministically, via Tree-sitter, never via the LLM --
whether its signature changed. No DB access here; the DB-backed lookup of indexed
chunks lives in service.py.
"""

import textwrap
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from app.parsing.base import LanguageParser, ParsedChunk
from app.review.diff_parser import FileDiff, Hunk
from app.review.signature import diff_signatures, extract_signatures

_RENAME_SIMILARITY_THRESHOLD = 0.6
_SIGNATURE_KINDS = ("function", "method")


@dataclass(slots=True)
class IndexedChunkRef:
    """The base-branch index's view of one chunk -- decoupled from the SQLAlchemy
    model so this module stays DB-free and unit-testable with synthetic data."""

    chunk_id: Any
    symbol_name: str
    kind: str
    start_line: int
    end_line: int
    source: str


@dataclass(slots=True)
class ChangedSymbol:
    file_path: str
    symbol_name: str
    old_symbol_name: str | None  # set only when change_type == "renamed"
    kind: str
    language: str
    change_type: str  # "added" | "modified" | "removed" | "renamed"
    signature_changed: bool
    signature_change_details: list[str]
    old_start_line: int | None
    old_end_line: int | None
    new_start_line: int | None
    new_end_line: int | None
    indexed_chunk_id: Any | None  # the base-branch Chunk.id, if this symbol existed in the index
    new_source: str | None  # best-effort new text, for building retrieval queries


def _overlaps(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    return max(a_start, b_start) <= min(a_end, b_end)


def _overlaps_any_hunk_old_range(chunk: IndexedChunkRef, hunks: list[Hunk]) -> bool:
    return any(_overlaps(chunk.start_line, chunk.end_line, *hunk.old_range) for hunk in hunks)


def _hunk_new_line_map(hunk: Hunk) -> list[int]:
    """index i -> the absolute new-file line number of the (i+1)-th line of
    `hunk.new_text()` (which only contains "add"/"context" lines, in order)."""
    return [line.new_line_no for line in hunk.lines if line.tag in ("add", "context") and line.new_line_no is not None]


def _def_line_removed(old_chunk: IndexedChunkRef, hunks: list[Hunk]) -> bool:
    return any(
        old_chunk.start_line in hunk.removed_line_numbers
        for hunk in hunks
        if _overlaps(old_chunk.start_line, old_chunk.start_line, *hunk.old_range)
    )


def _translate_old_line_to_new(old_line: int, hunks: list[Hunk]) -> int | None:
    """The new-file line number a (still-present, unchanged) old line maps to, found
    via the context line that carries both numbers. None if that old line isn't shown
    as context in any hunk (e.g. it was itself edited)."""
    for hunk in hunks:
        for line in hunk.lines:
            if line.tag == "context" and line.old_line_no == old_line:
                return line.new_line_no
    return None


def _with_absolute_new_lines(chunk: ParsedChunk, line_map: list[int]) -> ParsedChunk:
    start = line_map[chunk.start_line - 1] if 1 <= chunk.start_line <= len(line_map) else chunk.start_line
    end = line_map[chunk.end_line - 1] if 1 <= chunk.end_line <= len(line_map) else chunk.end_line
    return ParsedChunk(
        file_path=chunk.file_path,
        symbol_name=chunk.symbol_name,
        kind=chunk.kind,
        start_line=start,
        end_line=end,
        parent_symbol=chunk.parent_symbol,
        source=chunk.source,
        imports=chunk.imports,
        calls=chunk.calls,
    )


def _signature_diff_if_applicable(old_source: str, old_name: str, new_source: str, new_name: str, language: str) -> list[str]:
    old_sig = extract_signatures(textwrap.dedent(old_source), language).get(old_name)
    new_sig = extract_signatures(textwrap.dedent(new_source), language).get(new_name)
    if old_sig is None or new_sig is None:
        return []
    return diff_signatures(old_sig, new_sig)


def _normalize_body(source: str) -> str:
    """Body text with the def/signature line dropped, so a rename isn't penalized
    just because the old and new names differ on that one line."""
    lines = source.splitlines()
    body = lines[1:] if len(lines) > 1 else lines
    return "\n".join(line.strip() for line in body)


def _pair_renames(
    removed: list[IndexedChunkRef], added: list[ParsedChunk]
) -> tuple[list[tuple[IndexedChunkRef, ParsedChunk]], list[IndexedChunkRef], list[ParsedChunk]]:
    pairs: list[tuple[IndexedChunkRef, ParsedChunk]] = []
    used_added: set[int] = set()
    remaining_removed: list[IndexedChunkRef] = []

    for old_chunk in removed:
        best_idx: int | None = None
        best_ratio = 0.0
        for idx, candidate in enumerate(added):
            if idx in used_added or candidate.kind != old_chunk.kind:
                continue
            ratio = SequenceMatcher(None, _normalize_body(old_chunk.source), _normalize_body(candidate.source)).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_idx = idx
        if best_idx is not None and best_ratio >= _RENAME_SIMILARITY_THRESHOLD:
            pairs.append((old_chunk, added[best_idx]))
            used_added.add(best_idx)
        else:
            remaining_removed.append(old_chunk)

    remaining_added = [pc for idx, pc in enumerate(added) if idx not in used_added]
    return pairs, remaining_removed, remaining_added


def _build_removed(file_path: str, old: IndexedChunkRef, language: str) -> ChangedSymbol:
    return ChangedSymbol(
        file_path=file_path,
        symbol_name=old.symbol_name,
        old_symbol_name=None,
        kind=old.kind,
        language=language,
        change_type="removed",
        signature_changed=False,
        signature_change_details=[],
        old_start_line=old.start_line,
        old_end_line=old.end_line,
        new_start_line=None,
        new_end_line=None,
        indexed_chunk_id=old.chunk_id,
        new_source=None,
    )


def _build_added(file_path: str, new: ParsedChunk, language: str) -> ChangedSymbol:
    return ChangedSymbol(
        file_path=file_path,
        symbol_name=new.symbol_name,
        old_symbol_name=None,
        kind=new.kind,
        language=language,
        change_type="added",
        signature_changed=False,
        signature_change_details=[],
        old_start_line=None,
        old_end_line=None,
        new_start_line=new.start_line,
        new_end_line=new.end_line,
        indexed_chunk_id=None,
        new_source=new.source,
    )


def _build_body_only_modified(file_path: str, old: IndexedChunkRef, hunks: list[Hunk], language: str) -> ChangedSymbol:
    """The symbol's own def/class line was never touched -- only something inside its
    body was -- so by construction its signature can't have changed and it's still
    "modified", never "removed" or "renamed"."""
    new_start = _translate_old_line_to_new(old.start_line, hunks)
    new_end = _translate_old_line_to_new(old.end_line, hunks)
    return ChangedSymbol(
        file_path=file_path,
        symbol_name=old.symbol_name,
        old_symbol_name=None,
        kind=old.kind,
        language=language,
        change_type="modified",
        signature_changed=False,
        signature_change_details=[],
        old_start_line=old.start_line,
        old_end_line=old.end_line,
        new_start_line=new_start,
        new_end_line=new_end,
        indexed_chunk_id=old.chunk_id,
        new_source=old.source,  # best-effort stand-in; the body itself wasn't re-parsed
    )


def _build_modified_or_renamed(
    file_path: str, old: IndexedChunkRef, new: ParsedChunk, language: str, renamed: bool
) -> ChangedSymbol:
    details: list[str] = []
    if old.kind in _SIGNATURE_KINDS and new.kind in _SIGNATURE_KINDS:
        details = _signature_diff_if_applicable(old.source, old.symbol_name, new.source, new.symbol_name, language)
    return ChangedSymbol(
        file_path=file_path,
        symbol_name=new.symbol_name,
        old_symbol_name=old.symbol_name if renamed else None,
        kind=new.kind,
        language=language,
        change_type="renamed" if renamed else "modified",
        signature_changed=bool(details),
        signature_change_details=details,
        old_start_line=old.start_line,
        old_end_line=old.end_line,
        new_start_line=new.start_line,
        new_end_line=new.end_line,
        indexed_chunk_id=old.chunk_id,
        new_source=new.source,
    )


def map_file_changes(
    file_diff: FileDiff, parser: LanguageParser | None, indexed_chunks: list[IndexedChunkRef]
) -> list[ChangedSymbol]:
    """Figure out, per symbol touched by `file_diff`, what changed.

    `indexed_chunks` should be the base-branch index's chunks for this file (empty for
    a file that isn't indexed, e.g. a brand-new file). `parser` is the LanguageParser
    for this file's language (None for an unsupported language or a binary file --
    returns [] in that case, never raises).

    Each hunk's new-side text is parsed independently (never concatenated across
    hunks) to avoid synthesizing invalid syntax at hunk boundaries; a signature change
    always shows up as a diff line on the signature itself, so this is sufficient to
    detect it without needing the whole new file's content.
    """
    if file_diff.is_binary or parser is None:
        return []

    if file_diff.is_deleted:
        return [
            _build_removed(file_diff.lookup_path, chunk, parser.language)
            for chunk in indexed_chunks
            if _overlaps_any_hunk_old_range(chunk, file_diff.hunks)
        ]

    language = parser.language
    new_chunks: list[ParsedChunk] = []
    for hunk in file_diff.hunks:
        line_map = _hunk_new_line_map(hunk)
        for parsed in parser.parse(hunk.new_text(), file_diff.path):
            new_chunks.append(_with_absolute_new_lines(parsed, line_map))

    new_by_name = {pc.symbol_name: pc for pc in new_chunks}
    indexed_names = {c.symbol_name for c in indexed_chunks}

    changed: list[ChangedSymbol] = []
    unmatched_old: list[IndexedChunkRef] = []

    for old_chunk in indexed_chunks:
        if not _overlaps_any_hunk_old_range(old_chunk, file_diff.hunks):
            continue
        if not _def_line_removed(old_chunk, file_diff.hunks):
            # Only something inside the body was touched; the def/class line itself
            # is untouched, so this can't be a removal or rename -- and can't be a
            # signature change either, since that line wasn't edited.
            changed.append(_build_body_only_modified(file_diff.path, old_chunk, file_diff.hunks, language))
            continue
        new_chunk = new_by_name.get(old_chunk.symbol_name)
        if new_chunk is not None:
            changed.append(_build_modified_or_renamed(file_diff.path, old_chunk, new_chunk, language, renamed=False))
        else:
            unmatched_old.append(old_chunk)

    added_candidates = [pc for pc in new_chunks if pc.symbol_name not in indexed_names]
    pairs, leftover_old, leftover_new = _pair_renames(unmatched_old, added_candidates)

    for old_chunk, new_chunk in pairs:
        changed.append(_build_modified_or_renamed(file_diff.path, old_chunk, new_chunk, language, renamed=True))
    for old_chunk in leftover_old:
        changed.append(_build_removed(file_diff.path, old_chunk, language))
    for new_chunk in leftover_new:
        changed.append(_build_added(file_diff.path, new_chunk, language))

    return changed
