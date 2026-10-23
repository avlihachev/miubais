import shutil
import subprocess

import pytest
from miubais.cli import app
from typer.testing import CliRunner

runner = CliRunner()


@pytest.fixture
def course_repo(tmp_repo, fixture_course, monkeypatch):
    shutil.copytree(fixture_course / "x-sample", tmp_repo / "course" / "x-sample")
    monkeypatch.chdir(tmp_repo)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: None)
    return tmp_repo


def test_start_success_prints_next_command(course_repo):
    result = runner.invoke(app, ["start", "x-sample"])
    assert result.exit_code == 0
    assert "started x-sample at" in result.output
    assert "next: uv run miubais check x-sample" in result.output
    assert (course_repo / "workspace" / "x-sample").is_dir()


def test_start_unknown_id(course_repo):
    result = runner.invoke(app, ["start", "nope"])
    assert result.exit_code == 1
    assert "unknown exercise: nope" in result.output


def test_start_twice_refuses_with_hint_and_force_replaces(course_repo):
    runner.invoke(app, ["start", "x-sample"])
    marker = course_repo / "workspace" / "x-sample" / "mine.txt"
    marker.write_text("work")
    result = runner.invoke(app, ["start", "x-sample"])
    assert result.exit_code == 1
    assert "--force" in result.output
    assert marker.exists()
    result = runner.invoke(app, ["start", "x-sample", "--force"])
    assert result.exit_code == 0
    assert not marker.exists()


def test_reset_forgets_one_exercise_and_its_output(course_repo, monkeypatch):
    from miubais.paths import miubais_home
    from miubais.progress import Progress, load_progress, record, save_progress

    home = miubais_home()
    progress = Progress()
    record(progress, "x-sample", "01-add", "failed", None)
    record(progress, "other", "01-x", "passed", None)
    save_progress(progress, home, None)
    (home / "output" / "x-sample").mkdir(parents=True)
    (home / "output" / "x-sample" / "01-add.txt").write_text("boom")

    result = runner.invoke(app, ["reset", "x-sample"])
    assert result.exit_code == 0
    assert "forgot progress for x-sample" in result.output
    assert "x-sample" not in load_progress(home).exercises
    assert "other" in load_progress(home).exercises
    assert not (home / "output" / "x-sample").exists()


def test_reset_all_and_reset_without_arguments(course_repo):
    from miubais.paths import miubais_home
    from miubais.progress import Progress, load_progress, record, save_progress

    home = miubais_home()
    progress = Progress()
    record(progress, "x-sample", "01-add", "failed", None)
    save_progress(progress, home, None)
    assert runner.invoke(app, ["reset"]).exit_code == 1
    result = runner.invoke(app, ["reset", "--all"])
    assert result.exit_code == 0
    assert load_progress(home).exercises == {}
    assert "nothing recorded" in runner.invoke(app, ["reset", "x-sample"]).output


def test_start_force_forgets_progress(course_repo):
    from miubais.paths import miubais_home
    from miubais.progress import Progress, load_progress, record, save_progress

    home = miubais_home()
    runner.invoke(app, ["start", "x-sample"])
    progress = Progress()
    record(progress, "x-sample", "01-add", "passed", None)
    save_progress(progress, home, None)
    result = runner.invoke(app, ["start", "x-sample", "--force"])
    assert result.exit_code == 0
    assert "x-sample" not in load_progress(home).exercises


def test_reset_rewrites_the_workspace_mirror(course_repo):
    from miubais.paths import miubais_home
    from miubais.progress import Progress, record, save_progress

    mirror = course_repo / "workspace" / ".progress.json"
    progress = Progress()
    record(progress, "x-sample", "01-add", "failed", None)
    save_progress(progress, miubais_home(), mirror)
    assert runner.invoke(app, ["reset", "x-sample"]).exit_code == 0
    assert Progress.model_validate_json(mirror.read_text()).exercises == {}
