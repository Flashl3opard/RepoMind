import base64
import os
import shutil
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app.config import get_settings


class CloneError(RuntimeError):
    pass


@dataclass(slots=True)
class ClonedRepo:
    path: Path
    commit_sha: str


def _auth_extraheader_value(access_token: str) -> str:
    """A `http.extraheader` value authenticating as the token, GitHub App style (the
    literal username `x-access-token` with the installation token as the password).
    Passed via `-c` on the command line -- a one-off override for this invocation
    only, never written to the cloned repo's `.git/config`."""
    basic = base64.b64encode(f"x-access-token:{access_token}".encode()).decode()
    return f"AUTHORIZATION: basic {basic}"


def _redact(text: str, access_token: str | None) -> str:
    """Defense in depth: even though the token is never placed in the URL or logged
    directly, strip it out of any subprocess stderr/exception text before it's raised
    or logged, in case git itself ever echoes a header value back on some failure."""
    if not access_token:
        return text
    return text.replace(access_token, "***")


def clone_repository(url: str, *, access_token: str | None = None) -> ClonedRepo:
    """Shallow-clone `url` into a fresh temp dir and return its path + HEAD commit SHA.

    `access_token` (e.g. a GitHub App installation token, for cloning a private repo
    during webhook-triggered ingestion) is passed via a `git -c http.extraheader=...`
    override for this invocation only -- it is never interpolated into `url`, so it
    can't end up in the remote URL, `.git/config`, or `git`'s own argv-derived error
    text about the remote.

    Caller is responsible for calling `cleanup()` once done with the checkout.
    """
    if not url or url.startswith("-"):
        # Guards against the URL being interpreted as a `git` CLI flag.
        raise CloneError(f"Refusing to clone suspicious URL: {url!r}")

    settings = get_settings()
    dest = Path(tempfile.mkdtemp(prefix="repomind-", dir=settings.CLONE_WORKDIR))
    cmd = ["git", "clone", "--depth", "1", "--single-branch"]
    if access_token:
        cmd += ["-c", f"http.extraheader={_auth_extraheader_value(access_token)}"]
    cmd += ["--", url, str(dest)]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=300)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        shutil.rmtree(dest, ignore_errors=True)
        stderr = getattr(exc, "stderr", "") or str(exc)
        raise CloneError(f"git clone failed for {url}: {_redact(stderr, access_token)}") from exc

    commit_sha = _current_commit_sha(dest)
    return ClonedRepo(path=dest, commit_sha=commit_sha)


def _current_commit_sha(repo_path: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_path), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _force_remove_readonly(func, path, exc_info) -> None:
    # git marks objects/packfiles read-only; clear that bit so rmtree can delete them
    # (needed on Windows, where ignore_errors=True alone leaves them behind).
    os.chmod(path, stat.S_IWRITE)
    func(path)


def cleanup(cloned: ClonedRepo) -> None:
    shutil.rmtree(cloned.path, onexc=_force_remove_readonly)
