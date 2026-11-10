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


def clone_repository(url: str) -> ClonedRepo:
    """Shallow-clone `url` into a fresh temp dir and return its path + HEAD commit SHA.

    Caller is responsible for calling `cleanup()` once done with the checkout.
    """
    if not url or url.startswith("-"):
        # Guards against the URL being interpreted as a `git` CLI flag.
        raise CloneError(f"Refusing to clone suspicious URL: {url!r}")

    settings = get_settings()
    dest = Path(tempfile.mkdtemp(prefix="repomind-", dir=settings.CLONE_WORKDIR))
    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", "--single-branch", "--", url, str(dest)],
            check=True,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        shutil.rmtree(dest, ignore_errors=True)
        stderr = getattr(exc, "stderr", "") or str(exc)
        raise CloneError(f"git clone failed for {url}: {stderr}") from exc

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
