import os
import subprocess
from pathlib import Path

import pytest
from miubais.exercises import list_exercises
from miubais.paths import course_dir, repo_root

SAMPLES = sorted((repo_root() / "site" / "samples").glob("*/*.py"))


def module_pythonpath(module: str) -> str:
    exercise = next(e for e in list_exercises(course_dir()) if e.module == module)
    paths = [exercise.starter_dir / "src", exercise.dir / "lesson_support" / "src"]
    return os.pathsep.join(str(p) for p in paths if p.is_dir())


def lesson_for(sample: Path) -> Path:
    docs = repo_root() / "site" / "src" / "content" / "docs" / sample.parent.name
    return next(docs.glob(f"{sample.stem.split('-')[0]}-*.md*"))


def test_samples_exist():
    assert SAMPLES


@pytest.mark.parametrize("sample", SAMPLES, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_sample_output_matches_expected(sample):
    env = {**os.environ, "PYTHONPATH": module_pythonpath(sample.parent.name)}
    proc = subprocess.run(
        ["uv", "run", "--frozen", "python", str(sample)],
        cwd=repo_root(),
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == sample.with_suffix(".expected.txt").read_text()


@pytest.mark.parametrize("sample", SAMPLES, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_lesson_shows_the_sample_and_its_output(sample):
    lesson = lesson_for(sample).read_text()
    relative = sample.relative_to(repo_root()).as_posix()
    assert f"Sample: `{relative}`." in lesson
    assert f"```python\n{sample.read_text()}```" in lesson
    assert f"```\n{sample.with_suffix('.expected.txt').read_text()}```" in lesson
