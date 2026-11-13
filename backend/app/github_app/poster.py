"""Posts a finished review to GitHub as one review with inline comments.

Pure helpers (anchoring, message normalization, selection/capping, dedup, body
formatting) are kept separate from the actual network calls so the interesting logic
is unit-testable without a GitHub client at all.
"""

import hashlib
import logging
from dataclasses import dataclass

from app.github_app.client import GitHubApiError, GitHubClient
from app.review.diff_parser import new_side_ranges_by_file, parse_diff
from app.review.graph import ReviewResult
from app.review.schemas import VerifiedFinding

logger = logging.getLogger(__name__)

_SEVERITY_RANK = {"error": 0, "warning": 1, "info": 2}


def anchor_finding_line(finding: VerifiedFinding, new_ranges_by_file: dict[str, list[tuple[int, int]]]) -> int | None:
    """The line to anchor an inline comment to: the first line of the finding's own
    range that actually falls inside a hunk on the diff's new (RIGHT) side -- GitHub
    rejects a comment whose line isn't part of the diff. None if no such line exists
    (e.g. a "removed" finding that only has old-side coordinates), in which case the
    finding must be folded into the summary instead of posted inline."""
    ranges = new_ranges_by_file.get(finding["file"], [])
    for start, end in ranges:
        lo = max(finding["start_line"], start)
        hi = min(finding["end_line"], end)
        if lo <= hi:
            return lo
    return None


def normalize_message(message: str) -> str:
    """A hash stable across whitespace/case differences, for dedup against comments
    already posted on a previous review of the same PR."""
    collapsed = " ".join(message.lower().split())
    return hashlib.sha256(collapsed.encode("utf-8")).hexdigest()


def select_inline_and_overflow(
    findings: list[VerifiedFinding], max_inline: int
) -> tuple[list[VerifiedFinding], list[VerifiedFinding]]:
    """Most severe first; the first `max_inline` go inline, the rest overflow to the
    summary. Ties keep their relative order."""
    ranked = sorted(findings, key=lambda f: _SEVERITY_RANK.get(f["severity"], 99))
    return ranked[:max_inline], ranked[max_inline:]


def format_evidence_line(finding: VerifiedFinding, context: list[dict]) -> str:
    by_label = {c["label"]: c for c in context}
    locations = []
    for label in finding["evidence"]:
        chunk = by_label.get(label)
        if chunk is not None:
            locations.append(f"{chunk['file_path']}:{chunk['start_line']}-{chunk['end_line']}")
    return f"Evidence: {', '.join(locations)}" if locations else ""


def build_comment_body(finding: VerifiedFinding, context: list[dict]) -> str:
    evidence_line = format_evidence_line(finding, context)
    body = f"**[{finding['severity']}] {finding['category']}**\n\n{finding['message']}"
    if evidence_line:
        body += f"\n\n{evidence_line}"
    return body


@dataclass(slots=True)
class ExistingComment:
    file: str
    line: int
    message_hash: str


def existing_comment_keys(raw_comments: list[dict]) -> set[tuple[str, int, str]]:
    keys = set()
    for comment in raw_comments:
        path = comment.get("path")
        line = comment.get("line") or comment.get("original_line")
        body = comment.get("body", "")
        if path is not None and line is not None:
            keys.add((path, line, normalize_message(body)))
    return keys


def is_duplicate(finding: VerifiedFinding, line: int, existing: set[tuple[str, int, str]]) -> bool:
    return (finding["file"], line, normalize_message(finding["message"])) in existing


@dataclass(slots=True)
class ReviewPayload:
    body: str
    comments: list[dict]  # [{"path", "line", "body"}, ...] ready for the create-review API
    skipped_as_duplicate: int
    folded_into_summary: int  # overflow + unanchored findings whose text landed in `body`


def build_review_payload(
    result: ReviewResult,
    diff_text: str,
    existing_comments: set[tuple[str, int, str]],
    max_inline: int,
) -> ReviewPayload:
    """Pure: turns verified findings into a GitHub review body + inline comments,
    applying the anchoring guard, the inline cap (most severe first), and dedup
    against comments already posted on a previous review of this PR."""
    findings = result.verified_findings
    new_ranges = new_side_ranges_by_file(parse_diff(diff_text))

    inline_candidates, overflow = select_inline_and_overflow(findings, max_inline)

    comments: list[dict] = []
    folded: list[VerifiedFinding] = list(overflow)
    skipped_as_duplicate = 0

    for finding in inline_candidates:
        line = anchor_finding_line(finding, new_ranges)
        if line is None:
            folded.append(finding)
            continue
        if is_duplicate(finding, line, existing_comments):
            skipped_as_duplicate += 1
            continue
        comments.append({"path": finding["file"], "line": line, "body": build_comment_body(finding, result.context)})

    body_lines = [
        f"**RepoMind review** -- risk: {result.risk_level}",
        "",
        result.summary,
    ]
    if result.skip_notes:
        body_lines += ["", "Skipped:"] + [f"- {note}" for note in result.skip_notes]
    if folded:
        body_lines += ["", "Additional findings (not anchored inline):"]
        for finding in folded:
            evidence = format_evidence_line(finding, result.context)
            line_ref = f"{finding['file']}:{finding['start_line']}-{finding['end_line']}"
            body_lines.append(f"- **[{finding['severity']}] {finding['category']}** ({line_ref}) {finding['message']}" + (f" — {evidence}" if evidence else ""))

    return ReviewPayload(
        body="\n".join(body_lines),
        comments=comments,
        skipped_as_duplicate=skipped_as_duplicate,
        folded_into_summary=len(folded),
    )


def fold_all_into_summary(payload: ReviewPayload, comments_that_failed: list[dict]) -> ReviewPayload:
    """422 fallback: GitHub rejected the review with inline comments attached. Retry
    once with zero inline comments, folding their text into the body so nothing is
    silently lost."""
    extra_lines = ["", "Additional findings (could not be anchored as inline comments):"]
    for comment in comments_that_failed:
        extra_lines.append(f"- `{comment['path']}:{comment['line']}` {comment['body']}")
    return ReviewPayload(
        body=payload.body + "\n" + "\n".join(extra_lines),
        comments=[],
        skipped_as_duplicate=payload.skipped_as_duplicate,
        folded_into_summary=payload.folded_into_summary + len(comments_that_failed),
    )


@dataclass(slots=True)
class PostOutcome:
    posted: bool
    dry_run: bool
    inline_comment_count: int
    folded_into_summary: int
    skipped_as_duplicate: int
    retried_after_422: bool
    body: str


def post_review(
    client: GitHubClient,
    owner: str,
    repo: str,
    pr_number: int,
    head_sha: str,
    result: ReviewResult,
    diff_text: str,
    *,
    max_inline: int,
    dry_run: bool,
) -> PostOutcome:
    existing = existing_comment_keys(client.list_review_comments(owner, repo, pr_number)) if not dry_run else set()
    payload = build_review_payload(result, diff_text, existing, max_inline)

    if dry_run:
        logger.info(
            "REVIEW_DRY_RUN: would post review for %s/%s#%d (%d inline, %d folded, %d deduped)",
            owner, repo, pr_number, len(payload.comments), payload.folded_into_summary, payload.skipped_as_duplicate,
        )
        return PostOutcome(
            posted=False, dry_run=True, inline_comment_count=len(payload.comments),
            folded_into_summary=payload.folded_into_summary, skipped_as_duplicate=payload.skipped_as_duplicate,
            retried_after_422=False, body=payload.body,
        )

    try:
        client.create_review(owner, repo, pr_number, head_sha, payload.body, payload.comments)
        return PostOutcome(
            posted=True, dry_run=False, inline_comment_count=len(payload.comments),
            folded_into_summary=payload.folded_into_summary, skipped_as_duplicate=payload.skipped_as_duplicate,
            retried_after_422=False, body=payload.body,
        )
    except GitHubApiError as exc:
        if exc.status_code != 422 or not payload.comments:
            raise
        retried_payload = fold_all_into_summary(payload, payload.comments)
        client.create_review(owner, repo, pr_number, head_sha, retried_payload.body, [])
        return PostOutcome(
            posted=True, dry_run=False, inline_comment_count=0,
            folded_into_summary=retried_payload.folded_into_summary,
            skipped_as_duplicate=retried_payload.skipped_as_duplicate,
            retried_after_422=True, body=retried_payload.body,
        )
