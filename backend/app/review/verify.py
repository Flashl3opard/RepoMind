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


def _symbol_span(symbol: ChangedSymbol, finding: LLMFinding) -> int | None:
    """The size of whichever of the symbol's ranges (new- or old-side) overlaps the
    finding, or None if neither does. Checked against both sides because a finding
    about removed code may only make sense in old-file coordinates."""
    if symbol.file_path != finding.file:
        return None
    if (
        symbol.new_start_line is not None
        and symbol.new_end_line is not None
        and max(finding.start_line, symbol.new_start_line) <= min(finding.end_line, symbol.new_end_line)
    ):
        return symbol.new_end_line - symbol.new_start_line
    if (
        symbol.old_start_line is not None
        and symbol.old_end_line is not None
        and max(finding.start_line, symbol.old_start_line) <= min(finding.end_line, symbol.old_end_line)
    ):
        return symbol.old_end_line - symbol.old_start_line
    return None


def attribute_finding_to_symbol(finding: LLMFinding, changed_symbols: list[ChangedSymbol]) -> ChangedSymbol | None:
    """Attributes a finding to the smallest changed symbol whose range overlaps it.

    Two adjacent small functions (e.g. two one-line defs on consecutive lines) can
    both overlap a finding's line range; picking *any* overlapping symbol (the
    previous behavior) risked attributing a finding to the wrong neighbor and letting
    it ride through the breaking_change gate on a signature change that belongs to a
    different symbol entirely. Smallest-enclosing is the best deterministic tiebreak
    available without re-running the parser; if the smallest overlap is itself tied
    between two or more symbols, there's no principled way to pick one, so this
    returns None (no attribution) rather than guessing.
    """
    spans = [(span, symbol) for symbol in changed_symbols if (span := _symbol_span(symbol, finding)) is not None]
    if not spans:
        return None
    spans.sort(key=lambda pair: pair[0])
    smallest_span = spans[0][0]
    tied = [symbol for span, symbol in spans if span == smallest_span]
    return tied[0] if len(tied) == 1 else None


def passes_breaking_change_gate(
    finding: LLMFinding,
    changed_symbols: list[ChangedSymbol],
    context_by_label: dict[str, LabeledChunkState],
) -> bool:
    """Only applies to category == "breaking_change" (always True otherwise). Requires
    all of: (1) the finding attributes unambiguously to one changed symbol (see
    attribute_finding_to_symbol), (2) that symbol's deterministic signature-change-or-
    removal detector actually flagged it, and (3) at least one cited label is real
    caller evidence (touched by the PR or not -- either counts as "a caller exists")."""
    if finding.category != "breaking_change":
        return True

    symbol = attribute_finding_to_symbol(finding, changed_symbols)
    if symbol is None or not (symbol.signature_changed or symbol.change_type == "removed"):
        return False

    has_caller_evidence = any(
        (chunk := context_by_label.get(label)) is not None
        and (chunk["reason"].startswith("caller_of:") or chunk["reason"].startswith("stale_caller_of:"))
        for label in finding.evidence
    )
    return has_caller_evidence


def _is_real_caller_chunk(chunk: LabeledChunkState) -> bool:
    return chunk["reason"].startswith("caller_of:") or chunk["reason"].startswith("stale_caller_of:")


def passes_contract_change_gate(finding: LLMFinding, context_by_label: dict[str, LabeledChunkState]) -> bool:
    """Only applies to category == "contract_change" (always True otherwise).

    contract_change describes a behavioral change where the *declared* signature is
    unchanged, so there's no signature-diff signal to gate on the way
    passes_breaking_change_gate has. Instead the model must show its work: a cited
    label that's a real caller (per SymbolEdge-derived context, same as the
    breaking_change gate) AND a short verbatim quote of that caller's own usage,
    found in the caller chunk's actual source text (after whitespace normalization,
    so reflowed quotes don't spuriously fail). An invented quote, a quote pulled from
    a non-caller chunk, or no quote at all drops the finding.
    """
    if finding.category != "contract_change":
        return True
    if not finding.caller_usage or not finding.caller_usage.strip():
        return False

    quote = " ".join(finding.caller_usage.split())
    for label in finding.evidence:
        chunk = context_by_label.get(label)
        if chunk is None or not _is_real_caller_chunk(chunk):
            continue
        chunk_text = " ".join(chunk["source"].split())
        if quote in chunk_text:
            return True
    return False


def cap_contract_change_severity(finding: LLMFinding) -> LLMFinding:
    """contract_change findings are inherently more speculative than breaking_change
    (no signature diff backs them, only an LLM-identified behavioral shift plus a
    verified caller quote) -- capped at "warning", the middle of the three-tier
    info/warning/error scale, so they can never be reported as the most severe tier."""
    if finding.category == "contract_change" and finding.severity == "error":
        return finding.model_copy(update={"severity": "warning"})
    return finding


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
    *,
    strict_gates: bool = True,
) -> tuple[list[VerifiedFinding], int]:
    """Runs every deterministic rule in sequence. Returns (verified findings, how many
    were dropped).

    `strict_gates=False` is for the "naive" benchmark ablation mode only: its context
    (app.review.context_retrieval.build_naive_context) never contains caller/callee
    evidence by construction, so the breaking_change and contract_change gates --
    both of which *require* caller evidence -- would drop every finding in those
    categories regardless of whether the underlying issue was real. With it False,
    only hunk-bounds validity, dedup, and the per-file cap still apply; evidence-label
    existence and the two caller-evidence gates are skipped entirely."""
    old_ranges = old_side_ranges_by_file(file_diffs)
    new_ranges = new_side_ranges_by_file(file_diffs)

    survivors = [f for f in raw_findings if passes_hunk_bounds(f, old_ranges, new_ranges)]
    if strict_gates:
        valid_labels = {chunk["label"] for chunk in context}
        context_by_label = {chunk["label"]: chunk for chunk in context}
        survivors = [f for f in survivors if passes_valid_evidence(f, valid_labels)]
        survivors = [f for f in survivors if passes_breaking_change_gate(f, changed_symbols, context_by_label)]
        survivors = [f for f in survivors if passes_contract_change_gate(f, context_by_label)]
        survivors = [cap_contract_change_severity(f) for f in survivors]
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
            caller_usage=f.caller_usage,
        )
        for f in survivors
    ]
    dropped_count = len(raw_findings) - len(verified)
    return verified, dropped_count
