import json

from conftest import AllProbe, FakeRunner, NoProbe
from miubais.cli import app
from miubais.grader import TIMEOUT_EXIT, SubprocessRunner, run_exercise, run_stage
from miubais.progress import load_progress
from typer.testing import CliRunner


def test_run_exercise_stops_at_first_failure(sample_ex, started_ws):
    r = run_exercise(
        sample_ex, started_ws, runner=FakeRunner({"test_01_add.py": (1, "assert add(1,2) == 3")})
    )
    assert [x.status for x in r.results] == ["failed"]
    assert r.first_failure.stage.id == "01-add"


def test_live_stage_is_skipped_when_requirement_missing(sample_ex, started_ws):
    r = run_exercise(
        sample_ex, started_ws, runner=FakeRunner({"test_01_add.py": (0, "")}), probe=NoProbe()
    )
    assert [x.status for x in r.results] == ["passed", "skipped"]
    assert r.results[1].missing == ["claude-auth"]
    assert r.passed_stages == ["01-add"]


def test_all_stages_run_when_requirements_present(sample_ex, started_ws):
    runner = FakeRunner({})
    r = run_exercise(sample_ex, started_ws, runner=runner, probe=AllProbe())
    assert [x.status for x in r.results] == ["passed", "passed"]
    assert runner.commands[0][:4] == ["uv", "run", "--frozen", "pytest"]


def test_only_runs_single_stage(sample_ex, started_ws):
    runner = FakeRunner({})
    r = run_exercise(sample_ex, started_ws, only="02-live", runner=runner, probe=AllProbe())
    assert [x.stage.id for x in r.results] == ["02-live"]
    assert len(runner.commands) == 1


def test_stop_on_fail_false_continues(sample_ex, started_ws):
    r = run_exercise(
        sample_ex,
        started_ws,
        stop_on_fail=False,
        runner=FakeRunner({"test_01_add.py": (1, "boom")}),
        probe=AllProbe(),
    )
    assert [x.status for x in r.results] == ["failed", "passed"]


def test_failure_output_saved_and_recorded(sample_ex, started_ws, tmp_repo):
    run_exercise(sample_ex, started_ws, runner=FakeRunner({"test_01_add.py": (1, "boom")}))
    out = tmp_repo / "home" / "output" / "x-sample" / "01-add.txt"
    assert out.read_text() == "boom"
    rec = load_progress(tmp_repo / "home").exercises["x-sample"]["01-add"]
    assert rec.status == "failed" and rec.output_path == str(out)
    mirror = json.loads((started_ws.parent / ".progress.json").read_text())
    assert mirror["exercises"]["x-sample"]["01-add"]["status"] == "failed"


def test_run_stage_does_not_record(sample_ex, started_ws, tmp_repo):
    run_stage(sample_ex, sample_ex.stages[0], started_ws, runner=FakeRunner({}))
    assert not (tmp_repo / "home" / "progress.json").exists()


def test_subprocess_runner_captures_output_and_env(tmp_path):
    code, out = SubprocessRunner().run(
        ["python3", "-c", "import os;print(os.environ['MIUBAIS_WORKSPACE'])"],
        tmp_path,
        {"MIUBAIS_WORKSPACE": "ws"},
    )
    assert code == 0 and out.strip() == "ws"


def test_check_not_started_exits_2(fixture_course_cli):
    result = CliRunner().invoke(app, ["check", "x-sample"])
    assert result.exit_code == 2 and "miubais start x-sample" in result.output


def test_check_reports_and_exit_codes(fixture_course_cli, sample_ex, monkeypatch):
    from miubais import cli
    from miubais.workspace import start_exercise

    start_exercise(sample_ex, workspace=fixture_course_cli / "workspace")
    monkeypatch.setattr(cli, "SystemProbe", NoProbe)
    monkeypatch.setattr(cli, "SubprocessRunner", lambda: FakeRunner({"test_01_add.py": (0, "")}))
    ok = CliRunner().invoke(app, ["check", "x-sample"])
    assert ok.exit_code == 0
    assert "passed" in ok.output and "skipped (needs claude-auth)" in ok.output
    monkeypatch.setattr(cli, "SubprocessRunner", lambda: FakeRunner({"test_01_add.py": (1, "x")}))
    bad = CliRunner().invoke(app, ["check", "x-sample"])
    assert bad.exit_code == 1 and "failed" in bad.output
    assert "stage 01-add failed: add returns the sum" in bad.output
    assert "test_01_add.py" in bad.output and "read first: lesson x/01-adding" in bad.output
    assert "https://factory.lihachev.pro/x/01-adding/" in bad.output
    prog = CliRunner().invoke(app, ["progress"])
    assert prog.exit_code == 0 and "x-sample" in prog.output and "01-add" in prog.output


def test_stage_timeout_defaults_and_is_passed_to_runner(sample_ex, started_ws):
    runner = FakeRunner({})
    run_exercise(sample_ex, started_ws, runner=runner, probe=AllProbe())
    assert runner.timeouts == [600, 600]


def test_subprocess_runner_times_out(tmp_path):
    code, out = SubprocessRunner().run(
        ["python3", "-c", "import time; time.sleep(5)"], tmp_path, {}, timeout=0.5
    )
    assert code == TIMEOUT_EXIT and "timed out after 0.5 s" in out


def test_timed_out_stage_is_failed(sample_ex, started_ws):
    runner = FakeRunner({"test_01_add.py": (TIMEOUT_EXIT, "timed out after 600 s")})
    r = run_exercise(sample_ex, started_ws, runner=runner)
    assert r.results[0].status == "failed" and "timed out" in r.results[0].output


def test_progress_saved_after_each_stage(sample_ex, started_ws, tmp_repo):
    seen = []

    class Peeking(FakeRunner):
        def run(self, cmd, cwd, env, timeout=None):
            seen.append(load_progress(tmp_repo / "home").exercises.get("x-sample", {}).keys())
            return super().run(cmd, cwd, env, timeout)

    run_exercise(sample_ex, started_ws, runner=Peeking({}), probe=AllProbe())
    assert [list(k) for k in seen] == [[], ["01-add"]]


GUARD = ["-m", "not live", "-p", "miubais.offline_guard"]


def _has(cmd: list[str], part: list[str]) -> bool:
    return any(cmd[i : i + len(part)] == part for i in range(len(cmd)))


def test_offline_grading_deselects_live_tests_and_loads_the_guard(sample_ex, started_ws):
    runner = FakeRunner({})
    run_exercise(sample_ex, started_ws, runner=runner, probe=AllProbe(), offline=True)
    assert len(runner.commands) == 2
    assert all(_has(cmd, GUARD) for cmd in runner.commands)


def test_normal_grading_has_no_offline_guard(sample_ex, started_ws):
    runner = FakeRunner({})
    run_exercise(sample_ex, started_ws, runner=runner, probe=AllProbe())
    assert not any("miubais.offline_guard" in cmd for cmd in runner.commands)


def test_offline_live_stage_without_offline_tests_is_skipped_not_failed(sample_ex, started_ws):
    runner = FakeRunner({"test_02_live.py": (5, "no tests ran")})
    r = run_exercise(sample_ex, started_ws, runner=runner, probe=AllProbe(), offline=True)
    assert [x.status for x in r.results] == ["passed", "skipped"]
    runner = FakeRunner({"test_01_add.py": (5, "no tests ran")})
    r = run_exercise(sample_ex, started_ws, runner=runner, probe=AllProbe(), offline=True)
    assert r.results[0].status == "failed"


def test_live_grading_drops_an_inherited_skip_variable(sample_ex, started_ws):
    runner = FakeRunner({})
    run_exercise(sample_ex, started_ws, runner=runner, probe=AllProbe(), live=True)
    assert [env.get("MIUBAIS_SKIP_LIVE", "kept") for env in runner.envs] == ["kept", None]


def test_subprocess_runner_removes_variables_set_to_none(tmp_path, monkeypatch):
    monkeypatch.setenv("MIUBAIS_SKIP_LIVE", "1")
    code, out = SubprocessRunner().run(
        ["python3", "-c", "import os;print(os.environ.get('MIUBAIS_SKIP_LIVE', 'gone'))"],
        tmp_path,
        {"MIUBAIS_SKIP_LIVE": None},
    )
    assert code == 0 and out.strip() == "gone"


def _start_with_live_passed(fixture_course_cli, sample_ex, monkeypatch, runner):
    from miubais import cli
    from miubais.workspace import start_exercise

    start_exercise(sample_ex, workspace=fixture_course_cli / "workspace")
    monkeypatch.setattr(cli, "SystemProbe", AllProbe)
    monkeypatch.setattr(cli, "SubprocessRunner", lambda: runner)
    first = CliRunner().invoke(app, ["check", "x-sample"])
    assert first.exit_code == 0, first.output
    runner.commands.clear()


def test_check_skips_a_live_stage_that_already_passed(fixture_course_cli, sample_ex, monkeypatch):
    runner = FakeRunner({})
    _start_with_live_passed(fixture_course_cli, sample_ex, monkeypatch, runner)
    again = CliRunner().invoke(app, ["check", "x-sample"])
    assert again.exit_code == 0, again.output
    assert "passed (cached live)" in again.output
    assert [next(c for c in cmd if c.endswith(".py")) for cmd in runner.commands] == [
        str(sample_ex.dir / "tests/test_01_add.py")
    ]


def test_check_reruns_the_live_stage_when_asked(fixture_course_cli, sample_ex, monkeypatch):
    runner = FakeRunner({})
    _start_with_live_passed(fixture_course_cli, sample_ex, monkeypatch, runner)
    for args in (["--stage", "02-live"], ["--live"]):
        runner.commands.clear()
        res = CliRunner().invoke(app, ["check", "x-sample", *args])
        assert res.exit_code == 0, res.output
        assert "cached" not in res.output
        assert any(c.endswith("test_02_live.py") for cmd in runner.commands for c in cmd)


def test_check_runs_a_live_stage_whose_last_run_failed(fixture_course_cli, sample_ex, monkeypatch):
    from miubais import cli
    from miubais.workspace import start_exercise

    start_exercise(sample_ex, workspace=fixture_course_cli / "workspace")
    monkeypatch.setattr(cli, "SystemProbe", AllProbe)
    monkeypatch.setattr(cli, "SubprocessRunner", lambda: FakeRunner({"test_02_live.py": (1, "x")}))
    assert CliRunner().invoke(app, ["check", "x-sample"]).exit_code == 1
    runner = FakeRunner({})
    monkeypatch.setattr(cli, "SubprocessRunner", lambda: runner)
    res = CliRunner().invoke(app, ["check", "x-sample"])
    assert res.exit_code == 0 and "cached" not in res.output
    assert len(runner.commands) == 2


def test_skip_live_variable_reports_a_live_stage_as_skipped(
    fixture_course_cli, sample_ex, monkeypatch, tmp_repo
):
    from miubais import cli
    from miubais.workspace import start_exercise

    start_exercise(sample_ex, workspace=fixture_course_cli / "workspace")
    monkeypatch.setattr(cli, "SystemProbe", AllProbe)
    runner = FakeRunner({})
    monkeypatch.setattr(cli, "SubprocessRunner", lambda: runner)
    monkeypatch.setenv("MIUBAIS_SKIP_LIVE", "1")
    first = CliRunner().invoke(app, ["check", "x-sample"])
    assert first.exit_code == 0, first.output
    assert "skipped (MIUBAIS_SKIP_LIVE=1)" in first.output
    rec = load_progress(tmp_repo / "home").exercises["x-sample"]["02-live"]
    assert rec.status == "skipped"
    monkeypatch.delenv("MIUBAIS_SKIP_LIVE")
    runner.commands.clear()
    again = CliRunner().invoke(app, ["check", "x-sample"])
    assert again.exit_code == 0, again.output
    assert "cached" not in again.output
    assert any(c.endswith("test_02_live.py") for cmd in runner.commands for c in cmd)


def test_skip_live_failure_is_still_a_failure(sample_ex, started_ws, monkeypatch):
    monkeypatch.setenv("MIUBAIS_SKIP_LIVE", "1")
    runner = FakeRunner({"test_02_live.py": (1, "offline check failed")})
    r = run_exercise(sample_ex, started_ws, runner=runner, probe=AllProbe())
    assert [x.status for x in r.results] == ["passed", "failed"]


def test_a_skipped_live_stage_keeps_an_earlier_real_pass(
    sample_ex, started_ws, tmp_repo, monkeypatch
):
    run_exercise(sample_ex, started_ws, runner=FakeRunner({}), probe=AllProbe())
    monkeypatch.setenv("MIUBAIS_SKIP_LIVE", "1")
    r = run_exercise(sample_ex, started_ws, only="02-live", runner=FakeRunner({}), probe=AllProbe())
    assert r.results[0].status == "skipped"
    assert load_progress(tmp_repo / "home").exercises["x-sample"]["02-live"].status == "passed"


def _node_stage(ex, *, live=False):
    stage = ex.stages[0].model_copy(update={"requires": ["node"], "live": live})
    return ex, stage


class OnlyNode:
    def __init__(self, present):
        self.present = present

    def has(self, req):
        return self.present and req == "node"


def test_non_live_stage_is_skipped_when_requirement_missing(sample_ex, started_ws):
    ex, stage = _node_stage(sample_ex)
    for offline in (False, True):
        runner = FakeRunner({})
        r = run_stage(ex, stage, started_ws, probe=OnlyNode(False), runner=runner, offline=offline)
        assert r.status == "skipped" and r.missing == ["node"]
        assert runner.commands == []


def test_non_live_stage_runs_when_requirement_present(sample_ex, started_ws):
    ex, stage = _node_stage(sample_ex)
    r = run_stage(ex, stage, started_ws, probe=OnlyNode(True), runner=FakeRunner({}), offline=True)
    assert r.status == "passed"


def test_live_stage_with_missing_requirement_still_runs_offline(sample_ex, started_ws):
    ex, stage = _node_stage(sample_ex, live=True)
    r = run_stage(ex, stage, started_ws, probe=OnlyNode(False), runner=FakeRunner({}), offline=True)
    assert r.status == "skipped" and r.reason and not r.missing


def test_check_warns_when_the_starter_moved_on(
    fixture_course_cli, fixture_course, monkeypatch, tmp_path
):
    import shutil

    from miubais import cli
    from miubais.exercises import load_exercise
    from miubais.workspace import start_exercise

    course = tmp_path / "moved-course"
    shutil.copytree(fixture_course / "x-sample", course / "x-sample")
    monkeypatch.setenv("MIUBAIS_COURSE", str(course))
    start_exercise(load_exercise(course / "x-sample"), workspace=fixture_course_cli / "workspace")
    (course / "x-sample" / "starter" / "src" / "sample_lab" / "extra.py").write_text("X = 1\n")
    monkeypatch.setattr(cli, "SystemProbe", NoProbe)
    monkeypatch.setattr(cli, "SubprocessRunner", lambda: FakeRunner({"test_01_add.py": (0, "")}))
    result = CliRunner().invoke(app, ["check", "x-sample"])
    assert "changed since you ran start" in result.output
    assert "new: src/sample_lab/extra.py" in result.output and "--force" in result.output
