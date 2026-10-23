import shutil

import pytest
import yaml
from miubais.exercises import ExerciseError, list_exercises, load_exercise


def copy_sample(fixture_course, tmp_path):
    dest = tmp_path / "x-sample"
    shutil.copytree(fixture_course / "x-sample", dest)
    return dest


def edit_stages(ex_dir, edit):
    path = ex_dir / "stages.yaml"
    data = yaml.safe_load(path.read_text())
    edit(data)
    path.write_text(yaml.safe_dump(data))


def test_load_sample_exercise(fixture_course):
    ex = load_exercise(fixture_course / "x-sample")
    assert ex.id == "x-sample" and ex.package == "sample_lab"
    assert [s.id for s in ex.stages] == ["01-add", "02-live"]
    assert ex.stages[1].live and ex.stages[1].requires == ["claude-auth"]
    assert ex.readme_path == ex.dir / "README.md"
    assert ex.starter_dir.is_dir() and ex.reference_dir.is_dir() and ex.tests_dir.is_dir()


def test_duplicate_stage_id_is_rejected(fixture_course, tmp_path):
    ex_dir = copy_sample(fixture_course, tmp_path)
    edit_stages(ex_dir, lambda d: d["stages"][1].update(id="01-add"))
    with pytest.raises(ExerciseError, match=r"01-add.*stages\.yaml|stages\.yaml.*01-add"):
        load_exercise(ex_dir)


def test_missing_tests_file_is_rejected(fixture_course, tmp_path):
    ex_dir = copy_sample(fixture_course, tmp_path)
    edit_stages(ex_dir, lambda d: d["stages"][0].update(tests="tests/nope.py"))
    with pytest.raises(ExerciseError, match="nope.py"):
        load_exercise(ex_dir)


def test_invalid_package_is_rejected(fixture_course, tmp_path):
    ex_dir = copy_sample(fixture_course, tmp_path)
    edit_stages(ex_dir, lambda d: d.update(package="not-valid"))
    with pytest.raises(ExerciseError, match="package"):
        load_exercise(ex_dir)


def test_missing_reference_dir_is_allowed(fixture_course, tmp_path):
    ex_dir = copy_sample(fixture_course, tmp_path)
    shutil.rmtree(ex_dir / "reference")
    ex = load_exercise(ex_dir)
    assert ex.has_reference is False
    assert ex.leak_terms_path == ex_dir / "tests" / ".leak-terms"


def test_missing_starter_dir_is_rejected(fixture_course, tmp_path):
    ex_dir = copy_sample(fixture_course, tmp_path)
    shutil.rmtree(ex_dir / "starter")
    with pytest.raises(ExerciseError, match="starter"):
        load_exercise(ex_dir)


def test_unknown_requirement_is_rejected(fixture_course, tmp_path):
    ex_dir = copy_sample(fixture_course, tmp_path)
    edit_stages(ex_dir, lambda d: d["stages"][1].update(requires=["bogus"]))
    with pytest.raises(ExerciseError, match="stages.yaml"):
        load_exercise(ex_dir)


def test_list_exercises_sorted_and_skips_non_exercises(fixture_course, tmp_path):
    shutil.copytree(fixture_course / "x-sample", tmp_path / "a-first")
    edit_stages(tmp_path / "a-first", lambda d: d.update(exercise="a-first"))
    shutil.copytree(fixture_course / "x-sample", tmp_path / "x-sample")
    (tmp_path / "notes").mkdir()
    assert [e.id for e in list_exercises(tmp_path)] == ["a-first", "x-sample"]


@pytest.mark.parametrize(
    ("edit", "match"),
    [
        (lambda d: d["stages"][0].update(requries=["docker"]), "requries"),
        (lambda d: d.update(titel="x"), "titel"),
        (lambda d: d["stages"][1].update(requires=[]), "requires"),
        (lambda d: d.update(stages=[]), "stages"),
        (lambda d: d.update(dir="/tmp"), "dir"),
        (lambda d: d["stages"][0].update(timeout=0), "timeout"),
    ],
    ids=[
        "stage-typo",
        "exercise-typo",
        "live-without-requires",
        "no-stages",
        "dir-key",
        "zero-timeout",
    ],
)
def test_schema_rejects_bad_stages(fixture_course, tmp_path, edit, match):
    ex_dir = copy_sample(fixture_course, tmp_path)
    edit_stages(ex_dir, edit)
    with pytest.raises(ExerciseError, match=match):
        load_exercise(ex_dir)


def test_stage_timeout_override(fixture_course, tmp_path):
    ex_dir = copy_sample(fixture_course, tmp_path)
    edit_stages(ex_dir, lambda d: d["stages"][0].update(timeout=30))
    ex = load_exercise(ex_dir)
    assert [s.timeout for s in ex.stages] == [30, 600]
