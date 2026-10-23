import shutil

import pytest
from miubais.exercises import load_exercise
from miubais.paths import course_dir
from miubais.tutor import evals
from miubais.tutor.evals import CASES_DIR, RUNS_DIR, load_cases

pytestmark = pytest.mark.skipif(
    not CASES_DIR.exists() or not RUNS_DIR.exists(), reason="tutor eval cases are private"
)


def test_shipped_cases_load():
    cases = load_cases(CASES_DIR)
    assert cases and all(c.file.endswith(".yaml") and c.must_mention_all for c in cases)


def test_shipped_cases_point_at_real_stages_and_replay():
    root = course_dir()
    cases = load_cases(CASES_DIR)
    for case in cases:
        stage_ids = [s.id for s in load_exercise(root / case.exercise).stages]
        assert case.stage in stage_ids
    hints = evals.load_run(RUNS_DIR / "latest.jsonl", cases)
    assert evals.score_hints(cases, hints, root).passed


def first_failure(output):
    return next(line for line in output.splitlines() if line.startswith("FAILED"))


@pytest.mark.slow
@pytest.mark.parametrize(
    "case", load_cases(CASES_DIR) if CASES_DIR.exists() else [], ids=lambda c: c.file
)
def test_shipped_case_snapshot_reproduces_its_failing_output(case, tmp_path):
    from miubais.grader import SubprocessRunner, run_stage

    ex = load_exercise(course_dir() / case.exercise)
    workspace = tmp_path / "ws"
    shutil.copytree(ex.starter_dir, workspace)
    evals._write_workspace(case, workspace)
    stage = next(s for s in ex.stages if s.id == case.stage)
    result = run_stage(ex, stage, workspace, runner=SubprocessRunner())
    assert result.status == "failed"
    assert first_failure(result.output) == first_failure(case.failing_output)
