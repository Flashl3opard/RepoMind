from app.github_app.service import (
    is_default_branch_push,
    is_draft_pr,
    is_fork_pr,
    should_enqueue_review,
)


def make_pr_payload(action="opened", draft=False, head_full_name="owner/repo", base_full_name="owner/repo") -> dict:
    return {
        "action": action,
        "pull_request": {
            "number": 1,
            "draft": draft,
            "head": {"sha": "abc123", "repo": {"full_name": head_full_name} if head_full_name else None},
        },
        "repository": {"full_name": base_full_name, "clone_url": "https://github.com/owner/repo.git", "default_branch": "main"},
        "installation": {"id": 99},
    }


def test_is_draft_pr_true():
    assert is_draft_pr(make_pr_payload(draft=True))


def test_is_draft_pr_false():
    assert not is_draft_pr(make_pr_payload(draft=False))


def test_is_fork_pr_false_when_same_repo():
    assert not is_fork_pr(make_pr_payload())


def test_is_fork_pr_true_when_different_repo():
    assert is_fork_pr(make_pr_payload(head_full_name="someoneelse/repo"))


def test_is_fork_pr_true_when_head_repo_deleted():
    assert is_fork_pr(make_pr_payload(head_full_name=None))


def test_should_enqueue_review_true_for_opened():
    should, reason = should_enqueue_review(make_pr_payload(action="opened"), allow_forks=False)
    assert should is True
    assert reason == ""


def test_should_enqueue_review_true_for_all_handled_actions():
    for action in ("opened", "synchronize", "reopened", "ready_for_review"):
        should, _ = should_enqueue_review(make_pr_payload(action=action), allow_forks=False)
        assert should is True


def test_should_enqueue_review_false_for_unhandled_action():
    should, reason = should_enqueue_review(make_pr_payload(action="closed"), allow_forks=False)
    assert should is False
    assert "unhandled action" in reason


def test_should_enqueue_review_false_for_draft():
    should, reason = should_enqueue_review(make_pr_payload(draft=True), allow_forks=False)
    assert should is False
    assert "draft" in reason


def test_should_enqueue_review_false_for_fork_when_forks_disallowed():
    should, reason = should_enqueue_review(make_pr_payload(head_full_name="fork/repo"), allow_forks=False)
    assert should is False
    assert "fork" in reason


def test_should_enqueue_review_true_for_fork_when_forks_allowed():
    should, _ = should_enqueue_review(make_pr_payload(head_full_name="fork/repo"), allow_forks=True)
    assert should is True


def test_is_default_branch_push_true():
    payload = {"ref": "refs/heads/main", "repository": {"default_branch": "main"}}
    assert is_default_branch_push(payload)


def test_is_default_branch_push_false_for_feature_branch():
    payload = {"ref": "refs/heads/feature-x", "repository": {"default_branch": "main"}}
    assert not is_default_branch_push(payload)


def test_is_default_branch_push_false_when_default_branch_missing():
    payload = {"ref": "refs/heads/main", "repository": {}}
    assert not is_default_branch_push(payload)
