import json

import pytest
from fastapi.testclient import TestClient

import app.api.dashboard as dashboard_module
from app.config import get_settings
from app.db.models import Repository, RepositoryStatus, ReviewRun, ReviewRunStatus
from app.db.session import get_db
from app.main import app

API_KEY = "test-dashboard-key"


@pytest.fixture
def client(monkeypatch, db_session) -> TestClient:
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    settings = get_settings()
    monkeypatch.setattr(settings, "DASHBOARD_API_KEY", API_KEY)

    test_client = TestClient(app)
    yield test_client

    app.dependency_overrides.pop(get_db, None)


def auth_headers(key: str = API_KEY) -> dict:
    return {"Authorization": f"Bearer {key}"}


def make_repo(db_session, status=RepositoryStatus.COMPLETED) -> Repository:
    repo = Repository(url="https://github.com/owner/repo.git", name="owner/repo", status=status, last_commit_sha="abc123")
    db_session.add(repo)
    db_session.commit()
    db_session.refresh(repo)
    return repo


def make_review_run(db_session, repo, **kwargs) -> ReviewRun:
    defaults = dict(
        repository_id=repo.id, pr_number=1, head_sha="sha1", status=ReviewRunStatus.DONE,
        finding_count=1, source="webhook", findings=[{"file": "a.py", "category": "bug_risk"}],
        summary="1 finding", risk_level="medium",
    )
    defaults.update(kwargs)
    run = ReviewRun(**defaults)
    db_session.add(run)
    db_session.commit()
    db_session.refresh(run)
    return run


# -- auth ---------------------------------------------------------------------------------


def test_repos_endpoint_requires_auth(client):
    response = client.get("/repos")
    assert response.status_code == 401


def test_repos_endpoint_rejects_wrong_key(client):
    response = client.get("/repos", headers=auth_headers("wrong-key"))
    assert response.status_code == 401


def test_health_does_not_require_auth(client):
    response = client.get("/health")
    assert response.status_code == 200


# -- GET /repos -----------------------------------------------------------------------------


def test_list_repos_empty(client):
    response = client.get("/repos", headers=auth_headers())
    assert response.status_code == 200
    assert response.json() == []


def test_list_repos_returns_counts_and_status(client, db_session):
    make_repo(db_session)
    response = client.get("/repos", headers=auth_headers())
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["full_name"] == "owner/repo"
    assert body[0]["status"] == "completed"
    assert body[0]["commit_sha"] == "abc123"
    assert body[0]["file_count"] == 0
    assert body[0]["chunk_count"] == 0


# -- GET /repos/{id}/reviews ------------------------------------------------------------------


def test_list_repo_reviews_404_for_missing_repo(client):
    import uuid

    response = client.get(f"/repos/{uuid.uuid4()}/reviews", headers=auth_headers())
    assert response.status_code == 404


def test_list_repo_reviews_newest_first(client, db_session):
    repo = make_repo(db_session)
    make_review_run(db_session, repo, pr_number=1, head_sha="sha1")
    make_review_run(db_session, repo, pr_number=2, head_sha="sha2")

    response = client.get(f"/repos/{repo.id}/reviews", headers=auth_headers())
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert body[0]["pr_number"] == 2  # most recently created


# -- GET /reviews/{run_id} -------------------------------------------------------------------


def test_get_review_run_404_for_missing_run(client):
    import uuid

    response = client.get(f"/reviews/{uuid.uuid4()}", headers=auth_headers())
    assert response.status_code == 404


def test_get_review_run_returns_full_detail(client, db_session):
    repo = make_repo(db_session)
    run = make_review_run(db_session, repo)

    response = client.get(f"/reviews/{run.id}", headers=auth_headers())
    assert response.status_code == 200
    body = response.json()
    assert body["summary"] == "1 finding"
    assert body["risk_level"] == "medium"
    assert body["findings"] == [{"file": "a.py", "category": "bug_risk"}]
    assert body["source"] == "webhook"


# -- GET /benchmark/latest -------------------------------------------------------------------


def test_benchmark_latest_404_when_no_results(client, monkeypatch, tmp_path):
    monkeypatch.setattr(dashboard_module, "BENCH_RESULTS_DIR", tmp_path / "does-not-exist")
    response = client.get("/benchmark/latest", headers=auth_headers())
    assert response.status_code == 404


def test_benchmark_latest_returns_most_recent_file(client, monkeypatch, tmp_path):
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    (results_dir / "20260101T000000Z.json").write_text(json.dumps({"summary": {"full": {"recall": 0.1}}}))
    (results_dir / "20260102T000000Z.json").write_text(json.dumps({"summary": {"full": {"recall": 0.9}}}))
    monkeypatch.setattr(dashboard_module, "BENCH_RESULTS_DIR", results_dir)

    response = client.get("/benchmark/latest", headers=auth_headers())
    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["full"]["recall"] == 0.9
    assert body["generated_at"] == "20260102T000000Z"
