import shutil
from pathlib import Path

import pytest
from conftest import AllProbe, FakeRunner, NoProbe
from miubais.exercises import ExerciseError, load_exercise
from miubais.grader import SubprocessRunner
from miubais.progress import load_progress
from miubais.selftest import selftest_all, selftest_exercise

pytestmark = pytest.mark.slow


@pytest.fixture
def ex_copy(sample_ex, tmp_path):
    shutil.copytree(sample_ex.dir, tmp_path / "x-sample")
    return load_exercise(tmp_path / "x-sample")


def test_selftest_sample_reference_passes_and_starter_fails(ex_copy, tmp_repo):
    r = selftest_exercise(ex_copy, runner=SubprocessRunner(), probe=NoProbe())
    assert r.reference_ok and r.starter_fails_first and r.ok


def test_selftest_does_not_touch_learner_progress(ex_copy, tmp_repo):
    selftest_exercise(ex_copy, runner=SubprocessRunner(), probe=NoProbe())
    assert load_progress(tmp_repo / "home").exercises == {}


def test_selftest_detects_broken_reference(ex_copy, tmp_repo):
    ex = ex_copy
    shutil.copy(
        ex.starter_dir / "src/sample_lab/__init__.py",
        ex.reference_dir / "src/sample_lab/__init__.py",
    )
    r = selftest_exercise(ex, runner=SubprocessRunner(), probe=NoProbe())
    assert not r.reference_ok and "01-add" in r.details


def test_selftest_all_writes_leak_terms(fixture_course, tmp_repo, tmp_path):
    shutil.copytree(fixture_course, tmp_path / "course", dirs_exist_ok=True)
    results = selftest_all(tmp_path / "course", runner=SubprocessRunner(), probe=NoProbe())
    assert [r.exercise_id for r in results] == ["x-sample"]
    assert (tmp_path / "course/x-sample/tests/.leak-terms").is_file()


def test_selftest_without_reference_raises(ex_copy, tmp_repo):
    shutil.rmtree(ex_copy.reference_dir)
    with pytest.raises(ExerciseError, match="no reference"):
        selftest_exercise(ex_copy, runner=FakeRunner({}), probe=NoProbe())


class EnvRunner(FakeRunner):
    def __init__(self, outcomes):
        super().__init__(outcomes)
        self.by_file: dict[str, dict] = {}

    def run(self, cmd, cwd, env, timeout=None):
        name = next(Path(c).name for c in cmd if c.endswith(".py"))
        self.by_file[name] = env
        return super().run(cmd, cwd, env, timeout)


def test_selftest_runs_live_stages_offline_by_default(ex_copy, tmp_repo):
    runner = EnvRunner({})
    r = selftest_exercise(ex_copy, runner=runner, probe=NoProbe())
    assert runner.by_file["test_02_live.py"]["MIUBAIS_SKIP_LIVE"] == "1"
    assert "MIUBAIS_SKIP_LIVE" not in runner.by_file["test_01_add.py"]
    assert r.offline_live == ["02-live"]


def test_selftest_fails_when_offline_tests_of_a_live_stage_fail(ex_copy, tmp_repo):
    runner = EnvRunner({"test_02_live.py": (1, "offline check failed")})
    r = selftest_exercise(ex_copy, runner=runner, probe=NoProbe())
    assert not r.reference_ok and "02-live" in r.details
    assert r.offline_live == []


def test_selftest_live_runs_without_the_skip_variable(ex_copy, tmp_repo):
    runner = EnvRunner({})
    r = selftest_exercise(ex_copy, runner=runner, probe=AllProbe(), live=True)
    assert runner.by_file["test_02_live.py"]["MIUBAIS_SKIP_LIVE"] is None
    assert r.offline_live == []


def test_selftest_fails_when_non_live_stage_lacks_requirement(ex_copy, tmp_repo):
    stage = ex_copy.stages[0].model_copy(update={"requires": ["node"]})
    ex = ex_copy.model_copy(update={"stages": [stage, *ex_copy.stages[1:]]})
    r = selftest_exercise(ex, runner=FakeRunner({}), probe=NoProbe())
    assert not r.reference_ok
    assert "needs node: install it to grade this module" in r.details
