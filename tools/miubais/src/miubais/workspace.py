import hashlib
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from miubais.exercises import Exercise
from miubais.paths import workspace_dir

STAMP = ".miubais-starter.json"


class WorkspaceError(Exception):
    pass


@dataclass(frozen=True)
class StarterDrift:
    stamped: bool
    added: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    untouched: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def starter_hashes(starter: Path) -> dict[str, str]:
    return {
        p.relative_to(starter).as_posix(): _sha(p)
        for p in sorted(starter.rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
    }


def workspace_path(ex: Exercise) -> Path:
    return workspace_dir() / ex.id


def is_started(ex: Exercise) -> bool:
    return workspace_path(ex).exists()


def _remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


def start_exercise(ex: Exercise, workspace: Path | None = None, *, force: bool = False) -> Path:
    workspace = workspace if workspace is not None else workspace_dir()
    target = workspace / ex.id
    if (target.exists() or target.is_symlink()) and not force:
        raise WorkspaceError(f"{target} already exists")
    staging = workspace / f".{ex.id}.tmp"
    if staging.exists():
        _remove(staging)
    try:
        shutil.copytree(
            ex.starter_dir, staging, ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
        )
        stamp = {"files": starter_hashes(ex.starter_dir)}
        (staging / STAMP).write_text(json.dumps(stamp, indent=2) + "\n")
        if target.exists() or target.is_symlink():
            _remove(target)
        staging.rename(target)
    except OSError as err:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        raise WorkspaceError(f"cannot create {target}: {err}") from err
    return target


def starter_drift(ex: Exercise, target: Path) -> StarterDrift | None:
    now = starter_hashes(ex.starter_dir)
    stamp = target / STAMP
    if not stamp.is_file():
        # copies made before stamps existed: only missing files can be detected
        missing = [f for f in now if not (target / f).exists()]
        return StarterDrift(stamped=False, added=missing) if missing else None
    then: dict[str, str] = json.loads(stamp.read_text())["files"]
    changed = [f for f in now if f in then and now[f] != then[f]]
    drift = StarterDrift(
        stamped=True,
        added=[f for f in now if f not in then],
        changed=changed,
        untouched=[f for f in changed if (target / f).is_file() and _sha(target / f) == then[f]],
        removed=[f for f in then if f not in now],
    )
    return drift if drift.added or drift.changed or drift.removed else None
