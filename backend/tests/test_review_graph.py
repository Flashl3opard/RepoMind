import pytest

from app.review.graph import ReviewTooLargeError, run_review
from app.review.schemas import LLMFinding, LLMReviewOutput
from tests.fakes import FakeChatModel, FakeEmbeddings

ADD_SIGNATURE_CHANGE_DIFF = """\
diff --git a/calculator.py b/calculator.py
--- a/calculator.py
+++ b/calculator.py
@@ -1,2 +1,2 @@
-def add(a, b):
-    return a + b
+def add(a, b, c=0):
+    return a + b + c
"""

NO_SYMBOL_CHANGE_DIFF = """\
diff --git a/calculator.py b/calculator.py
--- a/calculator.py
+++ b/calculator.py
@@ -7,0 +7,1 @@
+# trailing comment
"""


def test_review_flags_breaking_change_with_caller_evidence(db_session, ingested_repo):
    finding = LLMFinding(
        file="calculator.py", start_line=1, end_line=2, severity="error", category="breaking_change",
        message="add's signature changed and main still calls it with the old arity",
        evidence=["C1"],
    )
    chat_model = FakeChatModel(structured_outputs={"LLMReviewOutput": [LLMReviewOutput(findings=[finding])]})

    result = run_review(
        db_session, ingested_repo, ADD_SIGNATURE_CHANGE_DIFF,
        embeddings=FakeEmbeddings(), chat_model=chat_model,
    )

    assert result.risk_level == "high"
    assert len(result.verified_findings) == 1
    assert result.verified_findings[0]["category"] == "breaking_change"
    assert any(s["symbol"] == "add" and s["signature_changed"] for s in result.changed_symbols_debug)
    # the stale caller (main, untouched by this diff) must have been surfaced as context
    assert any(c["reason"].startswith("stale_caller_of:") for c in result.context_debug)


def test_review_drops_finding_with_invented_evidence_label(db_session, ingested_repo):
    finding = LLMFinding(
        file="calculator.py", start_line=1, end_line=2, severity="warning", category="style",
        message="minor style nit", evidence=["C99"],  # doesn't exist
    )
    chat_model = FakeChatModel(structured_outputs={"LLMReviewOutput": [LLMReviewOutput(findings=[finding])]})

    result = run_review(
        db_session, ingested_repo, ADD_SIGNATURE_CHANGE_DIFF,
        embeddings=FakeEmbeddings(), chat_model=chat_model,
    )

    assert result.verified_findings == []
    assert result.dropped_count == 1
    assert result.risk_level == "low"


def test_review_drops_out_of_bounds_finding(db_session, ingested_repo):
    finding = LLMFinding(
        file="calculator.py", start_line=9999, end_line=9999, severity="warning", category="style",
        message="out of bounds", evidence=["C1"],
    )
    chat_model = FakeChatModel(structured_outputs={"LLMReviewOutput": [LLMReviewOutput(findings=[finding])]})

    result = run_review(
        db_session, ingested_repo, ADD_SIGNATURE_CHANGE_DIFF,
        embeddings=FakeEmbeddings(), chat_model=chat_model,
    )

    assert result.verified_findings == []
    assert result.dropped_count == 1


def test_review_skips_llm_call_when_no_symbols_changed(db_session, ingested_repo):
    # an empty FakeChatModel will raise if .with_structured_output(...).invoke() is
    # ever called -- so completing without error proves the LLM was never invoked.
    chat_model = FakeChatModel()

    result = run_review(
        db_session, ingested_repo, NO_SYMBOL_CHANGE_DIFF,
        embeddings=FakeEmbeddings(), chat_model=chat_model,
    )

    assert result.verified_findings == []
    assert result.summary == "No issues found in the changed code."
    assert result.risk_level == "low"


def test_review_summary_and_risk_are_computed_not_from_llm(db_session, ingested_repo):
    findings = [
        LLMFinding(
            file="calculator.py", start_line=1, end_line=2, severity="info", category="style",
            message="consider a docstring", evidence=["C1"],
        )
    ]
    chat_model = FakeChatModel(structured_outputs={"LLMReviewOutput": [LLMReviewOutput(findings=findings)]})

    result = run_review(
        db_session, ingested_repo, ADD_SIGNATURE_CHANGE_DIFF,
        embeddings=FakeEmbeddings(), chat_model=chat_model,
    )

    assert len(result.verified_findings) == 1
    assert result.risk_level == "low"  # only an info/style finding -> low, deterministically
    assert "1 finding" in result.summary


def test_review_raises_too_large_when_file_cap_exceeded(db_session, ingested_repo):
    with pytest.raises(ReviewTooLargeError):
        run_review(
            db_session, ingested_repo, ADD_SIGNATURE_CHANGE_DIFF,
            embeddings=FakeEmbeddings(), chat_model=FakeChatModel(), max_files=0,
        )


def test_review_raises_too_large_when_diff_byte_cap_exceeded(db_session, ingested_repo):
    with pytest.raises(ReviewTooLargeError):
        run_review(
            db_session, ingested_repo, ADD_SIGNATURE_CHANGE_DIFF,
            embeddings=FakeEmbeddings(), chat_model=FakeChatModel(), max_diff_bytes=10,
        )
