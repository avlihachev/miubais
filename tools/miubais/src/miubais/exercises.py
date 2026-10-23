from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from miubais.requirements import Requirement


class ExerciseError(Exception):
    pass


DEFAULT_TIMEOUT = 600


class Stage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    tests: str
    live: bool = False
    requires: list[Requirement] = []
    timeout: int = Field(DEFAULT_TIMEOUT, gt=0)
    lesson: str | None = None

    @model_validator(mode="after")
    def _live_needs_requires(self) -> "Stage":
        if self.live and not self.requires:
            raise ValueError(f"stage {self.id!r} is live but lists no requires")
        return self


class Exercise(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    module: str
    title: str
    package: str
    dir: Path
    stages: list[Stage] = Field(min_length=1)

    @property
    def readme_path(self) -> Path:
        return self.dir / "README.md"

    @property
    def starter_dir(self) -> Path:
        return self.dir / "starter"

    @property
    def reference_dir(self) -> Path:
        return self.dir / "reference"

    @property
    def tests_dir(self) -> Path:
        return self.dir / "tests"

    @property
    def has_reference(self) -> bool:
        return self.reference_dir.is_dir()

    @property
    def leak_terms_path(self) -> Path:
        return self.tests_dir / ".leak-terms"


def load_exercise(dir: Path) -> Exercise:
    stages_file = dir / "stages.yaml"
    if not stages_file.is_file():
        raise ExerciseError(f"{stages_file}: file not found")
    try:
        raw = yaml.safe_load(stages_file.read_text())
    except yaml.YAMLError as exc:
        raise ExerciseError(f"{stages_file}: invalid yaml: {exc}") from exc
    if not isinstance(raw, dict):
        raise ExerciseError(f"{stages_file}: expected a mapping at top level")
    if "dir" in raw:
        raise ExerciseError(f"{stages_file}: 'dir' is not an allowed key")
    raw["id"] = raw.pop("exercise", None)
    try:
        exercise = Exercise(dir=dir, **raw)
    except ValidationError as exc:
        raise ExerciseError(f"{stages_file}: {exc}") from exc

    if not exercise.package.isidentifier():
        raise ExerciseError(
            f"{stages_file}: package {exercise.package!r} is not a valid identifier"
        )
    seen: set[str] = set()
    for stage in exercise.stages:
        if stage.id in seen:
            raise ExerciseError(f"{stages_file}: duplicate stage id {stage.id!r}")
        seen.add(stage.id)
        if not (dir / stage.tests).is_file():
            raise ExerciseError(
                f"{stages_file}: stage {stage.id!r} tests file {stage.tests} does not exist"
            )
    if not exercise.starter_dir.is_dir():
        raise ExerciseError(f"{dir}: missing directory starter/")
    return exercise


def list_exercises(course_dir: Path) -> list[Exercise]:
    exercises = [load_exercise(path.parent) for path in course_dir.glob("*/stages.yaml")]
    return sorted(exercises, key=lambda e: e.id)
