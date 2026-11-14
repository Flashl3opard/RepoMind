import base64
import subprocess

import pytest

from app.services import cloner
from app.services.cloner import CloneError, _auth_extraheader_value, clone_repository

SECRET_TOKEN = "ghs_supersecrettoken1234567890"  # pragma: allowlist secret


def test_auth_extraheader_value_encodes_x_access_token_basic_auth():
    header = _auth_extraheader_value(SECRET_TOKEN)
    assert header.startswith("AUTHORIZATION: basic ")
    encoded = header.removeprefix("AUTHORIZATION: basic ")
    decoded = base64.b64decode(encoded).decode()
    assert decoded == f"x-access-token:{SECRET_TOKEN}"


# -- fake git runner: the token must never show up in the URL or any logged argv ------


class RecordingRunner:
    """Stands in for subprocess.run; records every call's argv so tests can assert
    on exactly what would have been executed/logged, without needing a real git
    binary or network access."""

    def __init__(self, raise_error: bool = False, stderr: str = "fatal: repository not found") -> None:
        self.calls: list[list[str]] = []
        self.raise_error = raise_error
        self.stderr = stderr

    def __call__(self, cmd, **kwargs):
        self.calls.append(list(cmd))
        if self.raise_error:
            raise subprocess.CalledProcessError(128, cmd, output="", stderr=self.stderr)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")


def test_clone_with_access_token_never_puts_token_in_the_url_arg(monkeypatch, tmp_path):
    runner = RecordingRunner()
    monkeypatch.setattr(cloner.subprocess, "run", runner)
    monkeypatch.setattr(cloner, "_current_commit_sha", lambda path: "abc123")

    clone_repository("https://github.com/owner/private-repo.git", access_token=SECRET_TOKEN)

    assert len(runner.calls) == 1
    cmd = runner.calls[0]
    url_arg = cmd[cmd.index("--") + 1]
    assert url_arg == "https://github.com/owner/private-repo.git"
    assert SECRET_TOKEN not in url_arg
    # the token is carried only inside a `-c http.extraheader=...` override, base64-encoded
    assert all(SECRET_TOKEN not in arg for arg in cmd if not arg.startswith("AUTHORIZATION") and "extraheader" not in arg)


def test_clone_with_access_token_passes_extraheader_config_override(monkeypatch):
    runner = RecordingRunner()
    monkeypatch.setattr(cloner.subprocess, "run", runner)
    monkeypatch.setattr(cloner, "_current_commit_sha", lambda path: "abc123")

    clone_repository("https://github.com/owner/repo.git", access_token=SECRET_TOKEN)

    cmd = runner.calls[0]
    assert "-c" in cmd
    extraheader_arg = cmd[cmd.index("-c") + 1]
    assert extraheader_arg.startswith("http.extraheader=AUTHORIZATION: basic ")


def test_clone_without_access_token_has_no_extraheader_override(monkeypatch):
    runner = RecordingRunner()
    monkeypatch.setattr(cloner.subprocess, "run", runner)
    monkeypatch.setattr(cloner, "_current_commit_sha", lambda path: "abc123")

    clone_repository("https://github.com/owner/repo.git")

    cmd = runner.calls[0]
    assert "-c" not in cmd


def test_clone_failure_redacts_token_from_exception_message(monkeypatch):
    runner = RecordingRunner(raise_error=True, stderr=f"fatal: auth failed for token {SECRET_TOKEN}")
    monkeypatch.setattr(cloner.subprocess, "run", runner)

    with pytest.raises(CloneError) as exc_info:
        clone_repository("https://github.com/owner/repo.git", access_token=SECRET_TOKEN)

    assert SECRET_TOKEN not in str(exc_info.value)
    assert "***" in str(exc_info.value)


# -- real local clone: the token must never end up in the cloned repo's .git/config ---


def test_clone_with_access_token_does_not_persist_into_git_config(tiny_git_repo):
    cloned = clone_repository(f"file://{tiny_git_repo}", access_token=SECRET_TOKEN)
    try:
        git_config = (cloned.path / ".git" / "config").read_text()
        assert SECRET_TOKEN not in git_config
    finally:
        cloner.cleanup(cloned)
