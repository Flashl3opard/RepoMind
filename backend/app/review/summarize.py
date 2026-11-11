"""Deterministic summary + risk level for a finished review.

No LLM call here: risk level is computed from the verified findings, never asked from
the LLM (the task explicitly calls for this, and it also sidesteps needing a second
grounding/verify pass on top of an LLM-written summary).
"""

from app.review.schemas import RiskLevel, VerifiedFinding

_CATEGORY_LABELS = {
    "breaking_change": "breaking change",
    "bug_risk": "bug risk",
    "missing_test": "missing-test gap",
    "security": "security issue",
    "style": "style note",
}


def compute_risk_level(findings: list[VerifiedFinding]) -> RiskLevel:
    if any(f["category"] == "breaking_change" for f in findings) or any(f["severity"] == "error" for f in findings):
        return "high"
    if any(f["severity"] == "warning" for f in findings):
        return "medium"
    return "low"


def summarize_findings(findings: list[VerifiedFinding]) -> str:
    if not findings:
        return "No issues found in the changed code."

    files = sorted({f["file"] for f in findings})
    by_category: dict[str, int] = {}
    for finding in findings:
        by_category[finding["category"]] = by_category.get(finding["category"], 0) + 1

    category_summary = ", ".join(
        f"{count} {_CATEGORY_LABELS.get(category, category)}{'s' if count != 1 else ''}"
        for category, count in sorted(by_category.items(), key=lambda kv: -kv[1])
    )
    file_word = "file" if len(files) == 1 else "files"
    return f"{len(findings)} finding(s) across {len(files)} {file_word}: {category_summary}."
