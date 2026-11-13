from app.review.graph import ReviewResult
from evals.bench.run import evaluate, format_comparison_table, summarize


def make_result(findings=None, context=None) -> ReviewResult:
    return ReviewResult(
        verified_findings=findings or [],
        summary="", risk_level="low", dropped_count=0, skip_notes=[], files_reviewed=1,
        changed_symbols_debug=[], context_debug=[],
        context=context or [],
    )


def make_finding(file="calculator.py", category="breaking_change", evidence=None):
    return {
        "file": file, "start_line": 1, "end_line": 2, "severity": "error", "category": category,
        "message": "msg", "evidence": evidence or [],
    }


def make_case(case_id="001_add_required_param_add", mutation_type="add_required_param", is_negative=False):
    return {
        "case_id": case_id,
        "diff": "diff --git a/calculator.py b/calculator.py\n",
        "expected": {
            "mutation_type": mutation_type, "changed_symbol": "add", "changed_file": "calculator.py",
            "expected_caller_files": ["main.py", "test_calculator.py"], "is_negative": is_negative,
        },
    }


def test_evaluate_positive_case_hit_when_finding_cites_expected_caller():
    context = [{"label": "C1", "file_path": "main.py", "reason": "stale_caller_of:add", "source": "x"}]
    finding = make_finding(evidence=["C1"])
    result = make_result(findings=[finding], context=context)

    row = evaluate(make_case(), result, "full", elapsed=1.0, error=None)

    assert row["hit"] is True
    assert row["false_positive"] is None  # not a negative case
    assert row["evidence_valid"] is True


def test_evaluate_positive_case_miss_when_no_finding_on_changed_file():
    result = make_result(findings=[], context=[])
    row = evaluate(make_case(), result, "full", elapsed=1.0, error=None)
    assert row["hit"] is False


def test_evaluate_positive_case_miss_when_finding_cites_unrelated_file():
    context = [{"label": "C1", "file_path": "unrelated.py", "reason": "retrieved", "source": "x"}]
    finding = make_finding(evidence=["C1"])
    result = make_result(findings=[finding], context=context)

    row = evaluate(make_case(), result, "full", elapsed=1.0, error=None)
    assert row["hit"] is False


def test_evaluate_negative_case_false_positive_when_breaking_change_found():
    context = [{"label": "C1", "file_path": "main.py", "reason": "caller_of:add", "source": "x"}]
    finding = make_finding(category="breaking_change", evidence=["C1"])
    result = make_result(findings=[finding], context=context)

    row = evaluate(make_case(is_negative=True), result, "full", elapsed=1.0, error=None)

    assert row["false_positive"] is True
    assert row["hit"] is None  # not a positive case


def test_evaluate_negative_case_no_false_positive_for_non_breaking_finding():
    finding = make_finding(category="style", evidence=[])
    result = make_result(findings=[finding], context=[])
    row = evaluate(make_case(is_negative=True), result, "full", elapsed=1.0, error=None)
    assert row["false_positive"] is False


def test_evaluate_handles_none_result_as_error_case():
    row = evaluate(make_case(), None, "full", elapsed=0.5, error="boom")
    assert row["hit"] is False
    assert row["error"] == "boom"


def test_evaluate_evidence_valid_false_for_invented_label():
    finding = make_finding(evidence=["C99"])
    result = make_result(findings=[finding], context=[])
    row = evaluate(make_case(), result, "full", elapsed=1.0, error=None)
    assert row["evidence_valid"] is False


def test_summarize_computes_recall_and_false_positive_rate():
    rows = [
        {"mode": "full", "mutation_type": "add_required_param", "is_negative": False, "hit": True,
         "false_positive": None, "evidence_valid": True, "finding_count": 1, "latency_seconds": 1.0,
         "estimated_tokens": 10, "error": None},
        {"mode": "full", "mutation_type": "add_required_param", "is_negative": False, "hit": False,
         "false_positive": None, "evidence_valid": True, "finding_count": 0, "latency_seconds": 1.0,
         "estimated_tokens": 10, "error": None},
        {"mode": "full", "mutation_type": "add_optional_param", "is_negative": True, "hit": None,
         "false_positive": False, "evidence_valid": True, "finding_count": 0, "latency_seconds": 1.0,
         "estimated_tokens": 10, "error": None},
    ]
    summary = summarize(rows)
    assert summary["full"]["recall"] == 0.5
    assert summary["full"]["false_positive_rate"] == 0.0
    assert summary["full"]["case_count"] == 3


def test_summarize_separates_modes_independently():
    rows = [
        {"mode": "full", "mutation_type": "m", "is_negative": False, "hit": True, "false_positive": None,
         "evidence_valid": True, "finding_count": 1, "latency_seconds": 1.0, "estimated_tokens": 10, "error": None},
        {"mode": "diff_only", "mutation_type": "m", "is_negative": False, "hit": False, "false_positive": None,
         "evidence_valid": True, "finding_count": 0, "latency_seconds": 1.0, "estimated_tokens": 5, "error": None},
    ]
    summary = summarize(rows)
    assert summary["full"]["recall"] == 1.0
    assert summary["diff_only"]["recall"] == 0.0


def test_format_comparison_table_includes_both_modes():
    summary = {
        "full": {"recall": 0.8, "false_positive_rate": 0.1, "evidence_validity_rate": 1.0, "avg_latency_seconds": 1.5, "avg_estimated_tokens": 100, "error_count": 0},
        "diff_only": {"recall": 0.2, "false_positive_rate": 0.0, "evidence_validity_rate": 1.0, "avg_latency_seconds": 0.5, "avg_estimated_tokens": 20, "error_count": 0},
    }
    table = format_comparison_table(summary)
    assert "80.0%" in table
    assert "20.0%" in table
    assert "full" in table and "diff_only" in table


def test_format_comparison_table_handles_missing_mode():
    table = format_comparison_table({"full": {"recall": 1.0}})
    assert "n/a" in table
