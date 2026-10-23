import json
import shutil

import pytest
from conftest import AllProbe, FakeRunner
from miubais.exercises import load_exercise
from miubais.grader import SubprocessRunner, run_stage
from miubais.paths import repo_root
from miubais.selftest import selftest_exercise
from miubais.workspace import start_exercise

pytestmark = pytest.mark.slow

NEEDS = "needs Langfuse: docker compose -f course/m3-trace-lab/docker-compose.yml up -d"
LIVE_STAGE_TESTS = f'''import os

import pytest


def test_offline_part():
    assert True


@pytest.mark.live
@pytest.mark.skipif(os.environ.get("MIUBAIS_SKIP_LIVE") == "1", reason="MIUBAIS_SKIP_LIVE=1")
def test_live_part():
    if os.environ.get("LIVE_SAMPLE_UP") != "1":
        pytest.skip("{NEEDS}")
'''


class ReportingRunner(FakeRunner):
    def __init__(self, summary):
        super().__init__({})
        self.summary = summary

    def run(self, cmd, cwd, env, timeout=None):
        path = env.get("MIUBAIS_LIVE_REPORT")
        if path:
            with open(path, "w") as handle:
                json.dump(self.summary, handle)
        return super().run(cmd, cwd, env, timeout)


@pytest.fixture
def live_ex(sample_ex, tmp_path):
    shutil.copytree(sample_ex.dir, tmp_path / "x-sample")
    (tmp_path / "x-sample" / "tests" / "test_02_live.py").write_text(LIVE_STAGE_TESTS)
    return load_exercise(tmp_path / "x-sample")


@pytest.fixture
def live_ws(live_ex, tmp_repo):
    return start_exercise(live_ex, workspace=tmp_repo / "workspace")


def live_stage(ex):
    return next(s for s in ex.stages if s.live)


def test_a_live_stage_whose_live_tests_skip_is_skipped(sample_ex, started_ws):
    runner = ReportingRunner({"passed": 0, "skipped": [NEEDS]})
    result = run_stage(
        sample_ex, live_stage(sample_ex), started_ws, runner=runner, probe=AllProbe()
    )
    assert (result.status, result.reason) == ("skipped", NEEDS)
    assert "miubais.live_report" in runner.commands[0]


def test_a_live_stage_with_a_passing_live_test_passes(sample_ex, started_ws):
    runner = ReportingRunner({"passed": 1, "skipped": []})
    result = run_stage(
        sample_ex, live_stage(sample_ex), started_ws, runner=runner, probe=AllProbe()
    )
    assert result.status == "passed"


def test_offline_grading_does_not_ask_for_a_live_report(sample_ex, started_ws):
    runner = ReportingRunner({"passed": 0, "skipped": [NEEDS]})
    result = run_stage(sample_ex, live_stage(sample_ex), started_ws, runner=runner, offline=True)
    assert result.reason == "MIUBAIS_SKIP_LIVE=1"
    assert "MIUBAIS_LIVE_REPORT" not in runner.envs[0]
    assert "miubais.live_report" not in runner.commands[0]


def test_a_real_skipped_live_test_is_skipped_not_passed(live_ex, live_ws, monkeypatch):
    monkeypatch.delenv("LIVE_SAMPLE_UP", raising=False)
    result = run_stage(
        live_ex, live_stage(live_ex), live_ws, runner=SubprocessRunner(), probe=AllProbe()
    )
    assert (result.status, result.reason) == ("skipped", NEEDS), result.output


def test_a_real_live_test_that_runs_passes(live_ex, live_ws, monkeypatch):
    monkeypatch.setenv("LIVE_SAMPLE_UP", "1")
    result = run_stage(
        live_ex, live_stage(live_ex), live_ws, runner=SubprocessRunner(), probe=AllProbe()
    )
    assert result.status == "passed", result.output


def test_a_real_live_stage_offline_is_still_ok_offline(live_ex, live_ws):
    result = run_stage(
        live_ex, live_stage(live_ex), live_ws, runner=SubprocessRunner(), offline=True
    )
    assert (result.status, result.reason) == ("skipped", "MIUBAIS_SKIP_LIVE=1"), result.output


def test_selftest_live_fails_on_a_skipped_live_stage(live_ex, tmp_repo, monkeypatch):
    monkeypatch.delenv("LIVE_SAMPLE_UP", raising=False)
    r = selftest_exercise(live_ex, runner=SubprocessRunner(), probe=AllProbe(), live=True)
    assert not r.reference_ok
    assert f"02-live: skipped ({NEEDS})" in r.details


def test_a_skipif_on_a_missing_requirement_is_reported(tmp_path):
    test_file = tmp_path / "test_requirement.py"
    test_file.write_text(
        "import pytest\n\n\ndef test_offline():\n    assert True\n\n\n"
        "@pytest.mark.live\n"
        '@pytest.mark.skipif(True, reason="needs claude-auth")\n'
        "def test_live():\n    raise AssertionError\n"
    )
    report = tmp_path / "live.json"
    code, output = SubprocessRunner().run(
        ["uv", "run", "--frozen", "pytest", str(test_file), "-q", "-p", "miubais.live_report"],
        repo_root(),
        {"MIUBAIS_LIVE_REPORT": str(report)},
    )
    assert code == 0, output
    assert json.loads(report.read_text()) == {"passed": 0, "skipped": ["needs claude-auth"]}
