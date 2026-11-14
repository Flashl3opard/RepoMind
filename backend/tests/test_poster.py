from app.github_app.client import GitHubApiError
from app.github_app.poster import (
    PostOutcome,
    anchor_finding_line,
    build_comment_body,
    build_review_payload,
    existing_comment_keys,
    fold_all_into_summary,
    format_evidence_line,
    is_duplicate,
    normalize_message,
    post_review,
    select_inline_and_overflow,
)
from app.review.graph import ReviewResult
from app.review.schemas import VerifiedFinding

SIMPLE_DIFF = """\
diff --git a/calculator.py b/calculator.py
--- a/calculator.py
+++ b/calculator.py
@@ -1,2 +1,2 @@
-def add(a, b):
-    return a + b
+def add(a, b, c):
+    return a + b + c
"""


def make_finding(file="calculator.py", start=1, end=2, severity="error", category="breaking_change", message="msg", evidence=None) -> VerifiedFinding:
    return VerifiedFinding(
        file=file, start_line=start, end_line=end, severity=severity, category=category,
        message=message, evidence=["C1"] if evidence is None else evidence, caller_usage=None,
    )


def make_result(findings=None, context=None, risk="low", summary="ok", skip_notes=None) -> ReviewResult:
    return ReviewResult(
        verified_findings=findings or [], summary=summary, risk_level=risk, dropped_count=0,
        skip_notes=skip_notes or [], files_reviewed=1, changed_symbols_debug=[], context_debug=[],
        context=context or [{"label": "C1", "file_path": "calculator.py", "start_line": 1, "end_line": 2,
                              "symbol_name": "add", "reason": "caller_of:add", "sources": ["graph"], "score": 1.0,
                              "chunk_id": "x", "source": "..."}],
    )


# -- anchor_finding_line --------------------------------------------------------------


def test_anchor_finding_line_inside_hunk():
    finding = make_finding(start=1, end=2)
    ranges = {"calculator.py": [(1, 2)]}
    assert anchor_finding_line(finding, ranges) == 1


def test_anchor_finding_line_outside_any_hunk_returns_none():
    finding = make_finding(start=500, end=500)
    ranges = {"calculator.py": [(1, 2)]}
    assert anchor_finding_line(finding, ranges) is None


def test_anchor_finding_line_no_ranges_for_file_returns_none():
    finding = make_finding(file="other.py")
    assert anchor_finding_line(finding, {"calculator.py": [(1, 2)]}) is None


def test_anchor_finding_line_partial_overlap_anchors_to_overlap_start():
    finding = make_finding(start=5, end=10)
    ranges = {"calculator.py": [(8, 20)]}
    assert anchor_finding_line(finding, ranges) == 8


# -- normalize_message -----------------------------------------------------------------


def test_normalize_message_is_case_and_whitespace_insensitive():
    assert normalize_message("Hello   World") == normalize_message("hello world")


def test_normalize_message_differs_for_different_text():
    assert normalize_message("foo") != normalize_message("bar")


# -- select_inline_and_overflow --------------------------------------------------------


def test_select_inline_and_overflow_orders_by_severity():
    findings = [make_finding(severity="info"), make_finding(severity="error"), make_finding(severity="warning")]
    inline, overflow = select_inline_and_overflow(findings, max_inline=2)
    assert [f["severity"] for f in inline] == ["error", "warning"]
    assert [f["severity"] for f in overflow] == ["info"]


def test_select_inline_and_overflow_respects_cap():
    findings = [make_finding() for _ in range(5)]
    inline, overflow = select_inline_and_overflow(findings, max_inline=3)
    assert len(inline) == 3
    assert len(overflow) == 2


def test_select_inline_and_overflow_empty_overflow_when_under_cap():
    findings = [make_finding()]
    inline, overflow = select_inline_and_overflow(findings, max_inline=10)
    assert len(inline) == 1
    assert overflow == []


# -- existing_comment_keys / is_duplicate ----------------------------------------------


BOT_LOGIN = "repomind-bot[bot]"


def bot_comment(path, line, body) -> dict:
    return {"path": path, "line": line, "body": body, "user": {"login": BOT_LOGIN, "type": "Bot"}}


def human_comment(path, line, body, login="a-human") -> dict:
    return {"path": path, "line": line, "body": body, "user": {"login": login, "type": "User"}}


def test_existing_comment_keys_extracts_path_line_and_message_hash():
    raw = [bot_comment("a.py", 5, "Some message")]
    keys = existing_comment_keys(raw, BOT_LOGIN)
    assert (("a.py", 5, normalize_message("Some message"))) in keys


def test_existing_comment_keys_falls_back_to_original_line():
    raw = [{"path": "a.py", "original_line": 7, "body": "msg", "user": {"login": BOT_LOGIN, "type": "Bot"}}]
    keys = existing_comment_keys(raw, BOT_LOGIN)
    assert ("a.py", 7, normalize_message("msg")) in keys


def test_existing_comment_keys_ignores_comments_from_other_users():
    raw = [human_comment("a.py", 5, "Some message")]
    keys = existing_comment_keys(raw, BOT_LOGIN)
    assert keys == set()


def test_existing_comment_keys_ignores_same_login_if_not_type_bot():
    # a human account could theoretically share the login string; type must also match
    raw = [{"path": "a.py", "line": 5, "body": "msg", "user": {"login": BOT_LOGIN, "type": "User"}}]
    keys = existing_comment_keys(raw, BOT_LOGIN)
    assert keys == set()


def test_existing_comment_keys_ignores_comments_with_no_user_field():
    raw = [{"path": "a.py", "line": 5, "body": "msg"}]
    keys = existing_comment_keys(raw, BOT_LOGIN)
    assert keys == set()


def test_is_duplicate_true_when_key_matches():
    finding = make_finding(file="a.py", message="Some message")
    existing = {("a.py", 1, normalize_message("Some message"))}
    assert is_duplicate(finding, 1, existing)


def test_is_duplicate_false_when_line_differs():
    finding = make_finding(file="a.py", message="Some message")
    existing = {("a.py", 99, normalize_message("Some message"))}
    assert not is_duplicate(finding, 1, existing)


# -- format_evidence_line / build_comment_body -----------------------------------------


def test_format_evidence_line_resolves_label_to_location():
    finding = make_finding(evidence=["C1"])
    context = [{"label": "C1", "file_path": "main.py", "start_line": 3, "end_line": 5}]
    assert format_evidence_line(finding, context) == "Evidence: main.py:3-5"


def test_format_evidence_line_empty_when_no_matching_labels():
    finding = make_finding(evidence=["C99"])
    context = [{"label": "C1", "file_path": "main.py", "start_line": 3, "end_line": 5}]
    assert format_evidence_line(finding, context) == ""


def test_build_comment_body_includes_severity_category_message_and_evidence():
    finding = make_finding(severity="error", category="breaking_change", message="Hello", evidence=["C1"])
    context = [{"label": "C1", "file_path": "main.py", "start_line": 3, "end_line": 5}]
    body = build_comment_body(finding, context)
    assert "error" in body and "breaking_change" in body and "Hello" in body and "main.py:3-5" in body


# -- build_review_payload --------------------------------------------------------------


def test_build_review_payload_anchors_and_includes_inline_comments():
    finding = make_finding(start=1, end=2)
    result = make_result(findings=[finding])
    payload = build_review_payload(result, SIMPLE_DIFF, existing_comments=set(), max_inline=10)
    assert len(payload.comments) == 1
    assert payload.comments[0]["line"] == 1
    assert payload.folded_into_summary == 0
    assert payload.skipped_as_duplicate == 0


def test_build_review_payload_folds_unanchored_finding_into_summary():
    finding = make_finding(start=999, end=999)  # outside any hunk
    result = make_result(findings=[finding])
    payload = build_review_payload(result, SIMPLE_DIFF, existing_comments=set(), max_inline=10)
    assert payload.comments == []
    assert payload.folded_into_summary == 1
    assert "999" in payload.body


def test_build_review_payload_skips_duplicate_comment():
    finding = make_finding(start=1, end=2, message="dup message")
    result = make_result(findings=[finding])
    existing = {("calculator.py", 1, normalize_message("dup message"))}
    payload = build_review_payload(result, SIMPLE_DIFF, existing_comments=existing, max_inline=10)
    assert payload.comments == []
    assert payload.skipped_as_duplicate == 1


def test_build_review_payload_caps_inline_and_folds_overflow():
    findings = [make_finding(severity="error", start=1, end=1, message=f"m{i}") for i in range(3)]
    result = make_result(findings=findings)
    payload = build_review_payload(result, SIMPLE_DIFF, existing_comments=set(), max_inline=1)
    assert len(payload.comments) == 1
    assert payload.folded_into_summary == 2


def test_build_review_payload_body_mentions_risk_and_skip_notes():
    result = make_result(findings=[], risk="high", skip_notes=["skipped binary file x.png"])
    payload = build_review_payload(result, SIMPLE_DIFF, existing_comments=set(), max_inline=10)
    assert "high" in payload.body
    assert "x.png" in payload.body


# -- fold_all_into_summary (422 fallback) ----------------------------------------------


def test_fold_all_into_summary_moves_comments_into_body():
    finding = make_finding(start=1, end=2)
    result = make_result(findings=[finding])
    payload = build_review_payload(result, SIMPLE_DIFF, existing_comments=set(), max_inline=10)
    assert len(payload.comments) == 1

    retried = fold_all_into_summary(payload, payload.comments)
    assert retried.comments == []
    assert "calculator.py:1" in retried.body
    assert retried.folded_into_summary == 1


# -- post_review (with a fake GitHubClient) --------------------------------------------


class FakeClient:
    def __init__(self, existing_comments=None, fail_with_422_times=0):
        self.existing_comments = existing_comments or []
        self.fail_with_422_times = fail_with_422_times
        self.create_review_calls: list[dict] = []

    def list_review_comments(self, owner, repo, pr_number):
        return self.existing_comments

    def create_review(self, owner, repo, pr_number, commit_id, body, comments, event="COMMENT"):
        self.create_review_calls.append({"body": body, "comments": comments})
        if len(self.create_review_calls) <= self.fail_with_422_times:
            raise GitHubApiError("Unprocessable", 422, "line out of range")
        return {"id": len(self.create_review_calls)}


def test_post_review_dry_run_never_calls_create_review():
    finding = make_finding(start=1, end=2)
    result = make_result(findings=[finding])
    client = FakeClient()

    outcome = post_review(client, "owner", "repo", 1, "sha123", result, SIMPLE_DIFF, max_inline=10, dry_run=True)

    assert isinstance(outcome, PostOutcome)
    assert outcome.dry_run is True
    assert outcome.posted is False
    assert client.create_review_calls == []
    assert outcome.inline_comment_count == 1


def test_post_review_normal_success():
    finding = make_finding(start=1, end=2)
    result = make_result(findings=[finding])
    client = FakeClient()

    outcome = post_review(client, "owner", "repo", 1, "sha123", result, SIMPLE_DIFF, max_inline=10, dry_run=False)

    assert outcome.posted is True
    assert outcome.retried_after_422 is False
    assert len(client.create_review_calls) == 1
    assert len(client.create_review_calls[0]["comments"]) == 1


def test_post_review_retries_once_on_422_folding_comments_into_body():
    finding = make_finding(start=1, end=2, message="will be rejected inline")
    result = make_result(findings=[finding])
    client = FakeClient(fail_with_422_times=1)

    outcome = post_review(client, "owner", "repo", 1, "sha123", result, SIMPLE_DIFF, max_inline=10, dry_run=False)

    assert outcome.posted is True
    assert outcome.retried_after_422 is True
    assert len(client.create_review_calls) == 2
    assert client.create_review_calls[1]["comments"] == []
    assert "will be rejected inline" in client.create_review_calls[1]["body"]


def test_post_review_does_not_repeat_comment_already_posted():
    finding = make_finding(start=1, end=2, message="already posted")
    result = make_result(findings=[finding])
    existing = [bot_comment("calculator.py", 1, "already posted")]
    client = FakeClient(existing_comments=existing)

    outcome = post_review(
        client, "owner", "repo", 1, "sha123", result, SIMPLE_DIFF, max_inline=10, dry_run=False, bot_login=BOT_LOGIN
    )

    assert outcome.posted is True
    assert outcome.skipped_as_duplicate == 1
    assert client.create_review_calls[0]["comments"] == []


def test_post_review_a_human_comment_with_identical_text_does_not_suppress_ours():
    finding = make_finding(start=1, end=2, message="already posted")
    result = make_result(findings=[finding])
    existing = [human_comment("calculator.py", 1, "already posted")]
    client = FakeClient(existing_comments=existing)

    outcome = post_review(
        client, "owner", "repo", 1, "sha123", result, SIMPLE_DIFF, max_inline=10, dry_run=False, bot_login=BOT_LOGIN
    )

    assert outcome.skipped_as_duplicate == 0
    assert len(client.create_review_calls[0]["comments"]) == 1


def test_post_review_skips_dedup_entirely_when_bot_login_is_none():
    finding = make_finding(start=1, end=2, message="already posted")
    result = make_result(findings=[finding])
    existing = [bot_comment("calculator.py", 1, "already posted")]
    client = FakeClient(existing_comments=existing)

    outcome = post_review(
        client, "owner", "repo", 1, "sha123", result, SIMPLE_DIFF, max_inline=10, dry_run=False, bot_login=None
    )

    assert outcome.skipped_as_duplicate == 0
    assert len(client.create_review_calls[0]["comments"]) == 1
