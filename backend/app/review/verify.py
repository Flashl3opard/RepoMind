"""Deterministic verification of LLM-proposed findings. Nothing here calls an LLM --
that's the point: every rule is a plain function over data, so it's fully unit-testable
and never has to be "trusted" the way the findings it's checking are not.
"""

from collections import defaultdict
from difflib import SequenceMatcher

from app.agents.schemas import LabeledChunkState
from app.review.diff_parser import (
    FileDiff,
    new_side_ranges_by_file,
    old_side_ranges_by_file,
    range_overlaps_any,
)
from app.review.map_changes import ChangedSymbol
from app.review.schemas import LLMFinding, VerifiedFinding

_DEDUPE_SIMILARITY_THRESHOLD = 0.85
_SEVERITY_RANK = {"error": 0, "warning": 1, "info": 2}


def passes_hunk_bounds(
    finding: LLMFinding,
    old_ranges_by_file: dict[str, list[tuple[int, int]]],
    new_ranges_by_file: dict[str, list[tuple[int, int]]],
) -> bool:
    """A finding must land inside a changed hunk for its file, in either the new-side
    or old-side line numbering (a finding about removed code may only make sense in
    old-file coordinates, since that code no longer exists on the new side)."""
    new_ranges = new_ranges_by_file.get(finding.file, [])
    old_ranges = old_ranges_by_file.get(finding.file, [])
    return range_overlaps_any(finding.start_line, finding.end_line, new_ranges) or range_overlaps_any(
        finding.start_line, finding.end_line, old_ranges
    )


def passes_valid_evidence(finding: LLMFinding, valid_labels: set[str]) -> bool:
    """Every finding must cite at least one label, and every label it cites must be
    one we actually showed the model -- an invented or missing-evidence finding is
    dropped outright (stricter than the Q&A agent, which merely strips bad labels)."""
    return bool(finding.evidence) and all(label in valid_labels for label in finding.evidence)


def _changed_symbol_matches_finding(symbol: ChangedSymbol, finding: LLMFinding) -> bool:
    if symbol.file_path != finding.file:
        return False
    if (
        symbol.new_start_line is not None
        and symbol.new_end_line is not None
        and max(finding.start_line, symbol.new_start_line) <= min(finding.end_line, symbol.new_end_line)
    ):
        return True
    return (
        symbol.old_start_line is not None
        and symbol.old_end_line is not None
        and max(finding.start_line, symbol.old_start_line) <= min(finding.end_line, symbol.old_end_line)
    )


def passes_breaking_change_gate(
    finding: LLMFinding,
    changed_symbols: list[ChangedSymbol],
    context_by_label: dict[str, LabeledChunkState],
) -> bool:
    """Only applies to category == "breaking_change" (always True otherwise). Requires
    both: (1) the deterministic signature-change-or-removal detector actually flagged
    a symbol at this location, and (2) at least one cited label is real caller
    evidence (touched by the PR or not -- either counts as "a caller exists")."""
    if finding.category != "breaking_change":
        return True

    symbol_flagged = any(
        (symbol.signature_changed or symbol.change_type == "removed") and _changed_symbol_matches_finding(symbol, finding)
        for symbol in changed_symbols
    )
    if not symbol_flagged:
        return False

    has_caller_evidence = any(
        (chunk := context_by_label.get(label)) is not None
        and (chunk["reason"].startswith("caller_of:") or chunk["reason"].startswith("stale_caller_of:"))
        for label in finding.evidence
    )
    return has_caller_evidence


def _messages_similar(a: str, b: str) -> bool:
    return SequenceMatcher(None, a.strip().lower(), b.strip().lower()).ratio() >= _DEDUPE_SIMILARITY_THRESHOLD


def dedupe_findings(findings: list[LLMFinding]) -> list[LLMFinding]:
    """Drops findings that are near-identical to one already kept: same file,
    overlapping line range, same category, and a highly similar message."""
    kept: list[LLMFinding] = []
    for finding in findings:
        is_duplicate = any(
            finding.file == other.file
            and finding.category == other.category
            and max(finding.start_line, other.start_line) <= min(finding.end_line, other.end_line)
            and _messages_similar(finding.message, other.message)
            for other in kept
        )
        if not is_duplicate:
            kept.append(finding)
    return kept


def cap_findings_per_file(findings: list[LLMFinding], max_per_file: int) -> list[LLMFinding]:
    """Keeps at most `max_per_file` findings per file, most severe first, preserving
    relative order among equally-severe findings."""
    by_file: dict[str, list[LLMFinding]] = defaultdict(list)
    for finding in findings:
        by_file[finding.file].append(finding)

    capped: list[LLMFinding] = []
    for file_findings in by_file.values():
        ranked = sorted(file_findings, key=lambda f: _SEVERITY_RANK.get(f.severity, 99))
        capped.extend(ranked[:max_per_file])
    return capped


def verify_findings(
    raw_findings: list[LLMFinding],
    context: list[LabeledChunkState],
    changed_symbols: list[ChangedSymbol],
    file_diffs: list[FileDiff],
    max_per_file: int = 5,
) -> tuple[list[VerifiedFinding], int]:
    """Runs every deterministic rule in sequence. Returns (verified findings, how many
    were dropped)."""
    valid_labels = {chunk["label"] for chunk in context}
    context_by_label = {chunk["label"]: chunk for chunk in context}
    old_ranges = old_side_ranges_by_file(file_diffs)
    new_ranges = new_side_ranges_by_file(file_diffs)

    survivors = [f for f in raw_findings if passes_hunk_bounds(f, old_ranges, new_ranges)]
    survivors = [f for f in survivors if passes_valid_evidence(f, valid_labels)]
    survivors = [f for f in survivors if passes_breaking_change_gate(f, changed_symbols, context_by_label)]
    survivors = dedupe_findings(survivors)
    survivors = cap_findings_per_file(survivors, max_per_file)

    verified: list[VerifiedFinding] = [
        VerifiedFinding(
            file=f.file,
            start_line=f.start_line,
            end_line=f.end_line,
            severity=f.severity,
            category=f.category,
            message=f.message,
            evidence=list(f.evidence),
        )
        for f in survivors
    ]
    dropped_count = len(raw_findings) - len(verified)
    return verified, dropped_count
