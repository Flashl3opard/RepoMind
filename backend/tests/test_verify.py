from app.agents.schemas import LabeledChunkState
from app.review.diff_parser import DiffLine, FileDiff, Hunk
from app.review.map_changes import ChangedSymbol
from app.review.schemas import LLMFinding
from app.review.verify import (
    cap_findings_per_file,
    dedupe_findings,
    passes_breaking_change_gate,
    passes_hunk_bounds,
    passes_valid_evidence,
    verify_findings,
)


def make_hunk(old_start, new_start, lines):
    hunk = Hunk(old_start=old_start, old_lines=0, new_start=new_start, new_lines=0, section_header="")
    oc, nc = old_start, new_start
    for tag, text in lines:
        if tag == "add":
            hunk.lines.append(DiffLine("add", text, None, nc))
            nc += 1
        elif tag == "remove":
            hunk.lines.append(DiffLine("remove", text, oc, None))
            oc += 1
        else:
            hunk.lines.append(DiffLine("context", text, oc, nc))
            oc += 1
            nc += 1
    hunk.old_lines = oc - old_start
    hunk.new_lines = nc - new_start
    return hunk


def make_finding(file="a.py", start=1, end=1, severity="warning", category="bug_risk", message="msg", evidence=None):
    return LLMFinding(
        file=file, start_line=start, end_line=end, severity=severity, category=category,
        message=message, evidence=["C1"] if evidence is None else evidence,
    )


def make_chunk_state(label="C1", reason="retrieved", file_path="a.py") -> LabeledChunkState:
    return LabeledChunkState(
        label=label, chunk_id="id", file_path=file_path, symbol_name="foo", start_line=1, end_line=5,
        source="def foo(): pass", reason=reason, sources=["vector"], score=1.0,
    )


def make_changed_symbol(
    file_path="a.py", symbol_name="foo", change_type="modified", signature_changed=False,
    new_start=10, new_end=15, old_start=10, old_end=14,
):
    return ChangedSymbol(
        file_path=file_path, symbol_name=symbol_name, old_symbol_name=None, kind="function",
        language="python", change_type=change_type, signature_changed=signature_changed,
        signature_change_details=[], old_start_line=old_start, old_end_line=old_end,
        new_start_line=new_start, new_end_line=new_end, indexed_chunk_id="id", new_source="def foo(): pass",
    )


# -- passes_hunk_bounds --------------------------------------------------------------


def test_hunk_bounds_passes_when_inside_new_range():
    fd = FileDiff(old_path="a.py", new_path="a.py", hunks=[make_hunk(10, 10, [("add", "x = 1")])])
    finding = make_finding(file="a.py", start=10, end=10)
    old_ranges, new_ranges = {}, {"a.py": [fd.hunks[0].new_range]}
    assert passes_hunk_bounds(finding, old_ranges, new_ranges)


def test_hunk_bounds_fails_when_outside_any_range():
    finding = make_finding(file="a.py", start=500, end=500)
    assert not passes_hunk_bounds(finding, {}, {"a.py": [(1, 10)]})


def test_hunk_bounds_fails_for_different_file():
    finding = make_finding(file="b.py", start=5, end=5)
    assert not passes_hunk_bounds(finding, {}, {"a.py": [(1, 10)]})


def test_hunk_bounds_passes_via_old_side_range_for_removed_code():
    finding = make_finding(file="a.py", start=20, end=22)
    assert passes_hunk_bounds(finding, {"a.py": [(20, 22)]}, {})


# -- passes_valid_evidence ------------------------------------------------------------


def test_valid_evidence_passes_when_all_labels_exist():
    finding = make_finding(evidence=["C1", "C2"])
    assert passes_valid_evidence(finding, {"C1", "C2", "C3"})


def test_valid_evidence_fails_when_any_label_invented():
    finding = make_finding(evidence=["C1", "C99"])
    assert not passes_valid_evidence(finding, {"C1", "C2"})


def test_valid_evidence_fails_when_empty():
    finding = make_finding(evidence=[])
    assert not passes_valid_evidence(finding, {"C1"})


# -- passes_breaking_change_gate -------------------------------------------------------


def test_breaking_change_gate_always_passes_for_other_categories():
    finding = make_finding(category="style", evidence=[])
    assert passes_breaking_change_gate(finding, [], {})


def test_breaking_change_gate_fails_without_signature_change_or_removal():
    finding = make_finding(category="breaking_change", start=10, end=10, evidence=["C1"])
    symbol = make_changed_symbol(signature_changed=False, change_type="modified")
    context = {"C1": make_chunk_state(reason="caller_of:foo")}
    assert not passes_breaking_change_gate(finding, [symbol], context)


def test_breaking_change_gate_fails_without_caller_evidence():
    finding = make_finding(category="breaking_change", start=10, end=10, evidence=["C1"])
    symbol = make_changed_symbol(signature_changed=True)
    context = {"C1": make_chunk_state(reason="retrieved")}  # not a caller
    assert not passes_breaking_change_gate(finding, [symbol], context)


def test_breaking_change_gate_passes_with_signature_change_and_caller():
    finding = make_finding(category="breaking_change", start=10, end=10, evidence=["C1"])
    symbol = make_changed_symbol(signature_changed=True)
    context = {"C1": make_chunk_state(reason="caller_of:foo")}
    assert passes_breaking_change_gate(finding, [symbol], context)


def test_breaking_change_gate_passes_with_removal_and_stale_caller():
    finding = make_finding(category="breaking_change", start=10, end=10, evidence=["C1"])
    symbol = make_changed_symbol(signature_changed=False, change_type="removed")
    context = {"C1": make_chunk_state(reason="stale_caller_of:foo")}
    assert passes_breaking_change_gate(finding, [symbol], context)


def test_breaking_change_gate_fails_when_finding_doesnt_overlap_the_symbol():
    finding = make_finding(category="breaking_change", start=1000, end=1000, evidence=["C1"])
    symbol = make_changed_symbol(signature_changed=True)  # at lines 10-15/10-14
    context = {"C1": make_chunk_state(reason="caller_of:foo")}
    assert not passes_breaking_change_gate(finding, [symbol], context)


# -- dedupe_findings --------------------------------------------------------------------


def test_dedupe_drops_near_identical_findings():
    f1 = make_finding(start=10, end=12, message="Changing this parameter breaks callers")
    f2 = make_finding(start=11, end=13, message="changing this parameter breaks callers!")
    result = dedupe_findings([f1, f2])
    assert len(result) == 1


def test_dedupe_keeps_findings_with_different_categories():
    f1 = make_finding(start=10, end=12, category="bug_risk", message="same message here")
    f2 = make_finding(start=10, end=12, category="style", message="same message here")
    assert len(dedupe_findings([f1, f2])) == 2


def test_dedupe_keeps_findings_in_different_files():
    f1 = make_finding(file="a.py", start=10, end=12, message="same message here")
    f2 = make_finding(file="b.py", start=10, end=12, message="same message here")
    assert len(dedupe_findings([f1, f2])) == 2


def test_dedupe_keeps_dissimilar_messages_even_if_overlapping():
    f1 = make_finding(start=10, end=12, message="this breaks all downstream callers")
    f2 = make_finding(start=10, end=12, message="consider adding a docstring here")
    assert len(dedupe_findings([f1, f2])) == 2


# -- cap_findings_per_file --------------------------------------------------------------


def test_cap_limits_findings_per_file():
    findings = [make_finding(start=i, end=i, severity="info") for i in range(10)]
    capped = cap_findings_per_file(findings, max_per_file=3)
    assert len(capped) == 3


def test_cap_keeps_most_severe_first():
    findings = [
        make_finding(start=1, end=1, severity="info", message="a"),
        make_finding(start=2, end=2, severity="error", message="b"),
        make_finding(start=3, end=3, severity="warning", message="c"),
    ]
    capped = cap_findings_per_file(findings, max_per_file=2)
    assert [f.severity for f in capped] == ["error", "warning"]


def test_cap_applies_independently_per_file():
    findings = [make_finding(file="a.py", start=i, end=i) for i in range(3)] + [
        make_finding(file="b.py", start=i, end=i) for i in range(3)
    ]
    capped = cap_findings_per_file(findings, max_per_file=2)
    assert len([f for f in capped if f.file == "a.py"]) == 2
    assert len([f for f in capped if f.file == "b.py"]) == 2


# -- verify_findings (composed) ----------------------------------------------------------


def test_verify_findings_end_to_end_drops_out_of_bounds_and_bad_evidence():
    fd = FileDiff(old_path="a.py", new_path="a.py", hunks=[make_hunk(10, 10, [("add", "x = 1")])])
    good = make_finding(file="a.py", start=10, end=10, category="style", evidence=["C1"])
    out_of_bounds = make_finding(file="a.py", start=500, end=500, category="style", evidence=["C1"])
    bad_evidence = make_finding(file="a.py", start=10, end=10, category="style", evidence=["C99"])
    context = [make_chunk_state(label="C1")]

    verified, dropped = verify_findings([good, out_of_bounds, bad_evidence], context, [], [fd])

    assert len(verified) == 1
    assert verified[0]["start_line"] == 10
    assert dropped == 2


def test_verify_findings_drops_unflagged_breaking_change():
    fd = FileDiff(old_path="a.py", new_path="a.py", hunks=[make_hunk(10, 10, [("add", "x = 1")])])
    finding = make_finding(file="a.py", start=10, end=10, category="breaking_change", evidence=["C1"])
    context = [make_chunk_state(label="C1", reason="caller_of:foo")]
    symbol = make_changed_symbol(signature_changed=False, change_type="modified", new_start=10, new_end=10)

    verified, dropped = verify_findings([finding], context, [symbol], [fd])

    assert verified == []
    assert dropped == 1


def test_verify_findings_keeps_valid_breaking_change():
    fd = FileDiff(old_path="a.py", new_path="a.py", hunks=[make_hunk(10, 10, [("add", "x = 1")])])
    finding = make_finding(file="a.py", start=10, end=10, category="breaking_change", evidence=["C1"])
    context = [make_chunk_state(label="C1", reason="caller_of:foo")]
    symbol = make_changed_symbol(signature_changed=True, new_start=10, new_end=10)

    verified, dropped = verify_findings([finding], context, [symbol], [fd])

    assert len(verified) == 1
    assert dropped == 0
