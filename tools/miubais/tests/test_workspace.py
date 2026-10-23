import shutil
import subprocess

import pytest
from miubais.exercises import load_exercise
from miubais.workspace import STAMP, WorkspaceError, is_started, start_exercise, starter_drift


def test_start_copies_starter_and_refuses_overwrite(fixture_course, tmp_repo):
    ex = load_exercise(fixture_course / "x-sample")
    target = start_exercise(ex, tmp_repo / "workspace")
    assert (target / "src" / "sample_lab" / "__init__.py").exists()
    with pytest.raises(WorkspaceError):
        start_exercise(ex, tmp_repo / "workspace")


def test_is_started_reflects_workspace(fixture_course, tmp_repo, monkeypatch):
    monkeypatch.chdir(tmp_repo)
    ex = load_exercise(fixture_course / "x-sample")
    assert not is_started(ex)
    start_exercise(ex, tmp_repo / "workspace")
    assert is_started(ex)


def test_force_replaces_existing_content(fixture_course, tmp_repo):
    ex = load_exercise(fixture_course / "x-sample")
    target = start_exercise(ex, tmp_repo / "workspace")
    (target / "mine.txt").write_text("work")
    start_exercise(ex, tmp_repo / "workspace", force=True)
    assert not (target / "mine.txt").exists()
    assert (target / "src" / "sample_lab" / "__init__.py").exists()
    assert not (tmp_repo / "workspace" / f".{ex.id}.tmp").exists()


def test_force_over_a_file_target(fixture_course, tmp_repo):
    ex = load_exercise(fixture_course / "x-sample")
    (tmp_repo / "workspace" / ex.id).write_text("not a dir")
    target = start_exercise(ex, tmp_repo / "workspace", force=True)
    assert target.is_dir()


def test_start_runs_no_subprocess(fixture_course, tmp_repo, monkeypatch):
    ex = load_exercise(fixture_course / "x-sample")
    monkeypatch.chdir(tmp_repo)

    def boom(*args, **kwargs):
        raise AssertionError("start must not shell out")

    monkeypatch.setattr(subprocess, "run", boom)
    start_exercise(ex, tmp_repo / "workspace")
    assert (tmp_repo / "workspace" / ex.id).is_dir()


def test_root_workspace_excludes_learner_copies():
    import tomllib

    from miubais.paths import repo_root

    root = tomllib.loads((repo_root() / "pyproject.toml").read_text())
    members = root["tool"]["uv"]["workspace"]["members"]
    assert not any(m.startswith("workspace") for m in members)
    assert "exercises" in root["dependency-groups"]
    assert "exercises" in root["tool"]["uv"]["default-groups"]


def drifting_course(fixture_course, tmp_path):
    shutil.copytree(fixture_course / "x-sample", tmp_path / "course" / "x-sample")
    return load_exercise(tmp_path / "course" / "x-sample")


def test_fresh_copy_has_no_drift(fixture_course, tmp_repo, tmp_path):
    ex = drifting_course(fixture_course, tmp_path)
    target = start_exercise(ex, tmp_repo / "workspace")
    assert (target / STAMP).is_file()
    assert starter_drift(ex, target) is None


def test_drift_lists_new_changed_and_removed_starter_files(fixture_course, tmp_repo, tmp_path):
    ex = drifting_course(fixture_course, tmp_path)
    target = start_exercise(ex, tmp_repo / "workspace")
    package = ex.starter_dir / "src" / "sample_lab"
    edited = min(package.glob("*.py"))
    edited.write_text(edited.read_text() + "\n# upstream change\n")
    (target / edited.relative_to(ex.starter_dir)).write_text("learner code\n")
    pyproject = ex.starter_dir / "pyproject.toml"
    pyproject.write_text(pyproject.read_text() + "\n")
    (package / "extra.py").write_text("X = 1\n")
    edited_rel = edited.relative_to(ex.starter_dir).as_posix()
    drift = starter_drift(ex, target)
    assert drift.stamped and drift.added == ["src/sample_lab/extra.py"]
    assert sorted(drift.changed) == sorted([edited_rel, "pyproject.toml"])
    assert drift.untouched == ["pyproject.toml"]
    pyproject.unlink()
    assert starter_drift(ex, target).removed == ["pyproject.toml"]


def test_unstamped_copy_reports_only_missing_files(fixture_course, tmp_repo, tmp_path):
    ex = drifting_course(fixture_course, tmp_path)
    target = start_exercise(ex, tmp_repo / "workspace")
    (target / STAMP).unlink()
    assert starter_drift(ex, target) is None
    (ex.starter_dir / "src" / "sample_lab" / "extra.py").write_text("X = 1\n")
    drift = starter_drift(ex, target)
    assert not drift.stamped and drift.added == ["src/sample_lab/extra.py"]
