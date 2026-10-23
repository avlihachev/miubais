import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

Status = Literal["passed", "failed", "skipped"]


class StageRecord(BaseModel):
    status: Status
    at: datetime
    output_path: str | None = None


class Progress(BaseModel):
    exercises: dict[str, dict[str, StageRecord]] = {}


def load_progress(home: Path) -> Progress:
    path = home / "progress.json"
    if not path.is_file():
        return Progress()
    return Progress.model_validate_json(path.read_text())


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def save_progress(p: Progress, home: Path, mirror: Path | None) -> None:
    text = p.model_dump_json(indent=2)
    _write_atomic(home / "progress.json", text)
    if mirror is not None:
        _write_atomic(mirror, text)


def record(
    p: Progress, exercise_id: str, stage_id: str, status: Status, output_path: str | None
) -> None:
    p.exercises.setdefault(exercise_id, {})[stage_id] = StageRecord(
        status=status, at=datetime.now(UTC), output_path=output_path
    )


def clear(p: Progress, exercise_id: str | None) -> list[str]:
    cleared = (
        [exercise_id] if exercise_id in p.exercises else [] if exercise_id else list(p.exercises)
    )
    for ex in cleared:
        del p.exercises[ex]
    return cleared
