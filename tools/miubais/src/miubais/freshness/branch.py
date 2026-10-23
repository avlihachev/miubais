import shutil
import subprocess
import tempfile
from datetime import date
from pathlib import Path

WATCHED = ("site/", "freshness/")


class BranchError(RuntimeError):
    pass


def _git(cwd: Path, *args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
        ).stdout
    except subprocess.CalledProcessError as err:
        raise BranchError(f"git {' '.join(args)} failed: {err.stderr.strip()}") from err


def clean_for_freshen(repo: Path) -> list[str]:
    dirty = []
    for line in _git(repo, "status", "--porcelain=v1").splitlines():
        status, path = line[:2], line[3:]
        if status != "??" and path.startswith(WATCHED):
            dirty.append(path)
    return dirty


def _branch_exists(repo: Path, branch: str) -> bool:
    return bool(_git(repo, "branch", "--list", branch).strip())


def ensure_clean(repo: Path) -> None:
    dirty = clean_for_freshen(repo)
    if dirty:
        raise BranchError(f"uncommitted changes under site/ or freshness/: {', '.join(dirty)}")


def commit_on_branch(repo: Path, date: date, files: list[tuple[Path, Path]]) -> str:
    ensure_clean(repo)
    branch = f"freshen/{date.isoformat()}"
    created = not _branch_exists(repo, branch)
    worktree = Path(tempfile.mkdtemp(prefix="miubais-freshen-"))
    failed = True
    try:
        if created:
            _git(repo, "worktree", "add", "-b", branch, str(worktree), "HEAD")
        else:
            _git(repo, "worktree", "add", "--force", str(worktree), branch)
        for source, dest in files:
            target = worktree / dest
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        if files:
            _git(worktree, "add", "--", *[dest.as_posix() for _, dest in files])
        if _git(worktree, "status", "--porcelain=v1").strip():
            _git(worktree, "commit", "-m", f"freshness: report {date.isoformat()}")
        sha = _git(worktree, "rev-parse", "HEAD").strip()
        failed = False
        return sha
    except (ValueError, OSError) as err:
        raise BranchError(f"could not stage freshness files: {err}") from err
    finally:
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(worktree)],
            cwd=repo,
            check=False,
            capture_output=True,
            text=True,
        )
        shutil.rmtree(worktree, ignore_errors=True)
        if created and failed:
            subprocess.run(
                ["git", "branch", "-D", branch], cwd=repo, check=False, capture_output=True
            )
