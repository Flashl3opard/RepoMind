from app.review.schemas import VerifiedFinding
from app.review.summarize import compute_risk_level, summarize_findings


def make_finding(file="a.py", severity="info", category="style") -> VerifiedFinding:
    return VerifiedFinding(
        file=file, start_line=1, end_line=1, severity=severity, category=category,
        message="msg", evidence=["C1"], caller_usage=None,
    )


def test_risk_level_low_with_no_findings():
    assert compute_risk_level([]) == "low"


def test_risk_level_low_with_only_info_findings():
    assert compute_risk_level([make_finding(severity="info")]) == "low"


def test_risk_level_medium_with_a_warning():
    assert compute_risk_level([make_finding(severity="warning")]) == "medium"


def test_risk_level_high_with_an_error():
    assert compute_risk_level([make_finding(severity="error")]) == "high"


def test_risk_level_high_with_breaking_change_even_if_severity_is_low():
    assert compute_risk_level([make_finding(severity="info", category="breaking_change")]) == "high"


def test_risk_level_high_outranks_medium():
    findings = [make_finding(severity="warning"), make_finding(severity="error")]
    assert compute_risk_level(findings) == "high"


def test_summary_no_findings():
    assert "No issues found" in summarize_findings([])


def test_summary_mentions_count_and_files():
    findings = [make_finding(file="a.py"), make_finding(file="b.py")]
    summary = summarize_findings(findings)
    assert "2 finding" in summary
    assert "2 files" in summary


def test_summary_singular_file_wording():
    summary = summarize_findings([make_finding(file="a.py")])
    assert "1 file:" in summary


def test_summary_mentions_category_breakdown():
    findings = [make_finding(category="breaking_change"), make_finding(category="breaking_change")]
    summary = summarize_findings(findings)
    assert "2 breaking changes" in summary
