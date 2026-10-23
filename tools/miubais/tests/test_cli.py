import json

import pytest
from miubais import paths
from miubais.cli import app
from typer.testing import CliRunner


def test_version_prints_package_version():
    result = CliRunner().invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "miubais" in result.output


def test_repo_root_finds_workspace_pyproject(tmp_repo, monkeypatch):
    monkeypatch.chdir(tmp_repo / "course")
    assert paths.repo_root() == tmp_repo


@pytest.mark.slow
def test_selftest_command_reports_ok(tmp_repo, tmp_path, fixture_course, monkeypatch):
    import shutil

    from conftest import NoProbe
    from miubais.cli import app
    from typer.testing import CliRunner

    monkeypatch.setattr("miubais.cli.SystemProbe", NoProbe)
    shutil.copytree(fixture_course, tmp_path / "c")
    res = CliRunner().invoke(app, ["selftest", "x-sample", "--course", str(tmp_path / "c")])
    assert res.exit_code == 0, res.output
    assert "x-sample: reference ok, starter fails first ok" in res.output
    assert "02-live ok (offline)" in res.output


def test_selftest_without_reference_exits_1_with_message(tmp_repo, fixture_course, monkeypatch):
    import shutil

    monkeypatch.chdir(tmp_repo)
    course = tmp_repo / "course"
    shutil.copytree(fixture_course / "x-sample", course / "x-sample")
    shutil.rmtree(course / "x-sample" / "reference")
    res = CliRunner().invoke(app, ["selftest", "--course", str(course)])
    assert res.exit_code == 1 and isinstance(res.exception, SystemExit)
    assert res.output.strip() == (
        "x-sample: no reference/ solution; selftest needs the private checkout"
    )


def _clean_docs(fixture_docs, dest):
    import shutil

    shutil.copytree(fixture_docs, dest, ignore=shutil.ignore_patterns("bad-*"))
    return dest


def _mock_make_http(monkeypatch):
    import httpx
    from miubais import cli

    def handler(request):
        url = str(request.url)
        if "pypi.org" in url:
            return httpx.Response(200, json={"info": {"version": "0.3.0"}})
        if "registry.npmjs.org" in url:
            return httpx.Response(200, json={"version": "0.42.6"})
        return httpx.Response(200)

    monkeypatch.setattr(
        cli, "make_http", lambda: httpx.Client(transport=httpx.MockTransport(handler))
    )
    monkeypatch.setattr(cli, "gh_api", lambda path: {})


def test_freshen_dry_run_prints_table_and_writes_nothing(tmp_repo, fixture_docs, monkeypatch):
    from miubais.cli import app
    from typer.testing import CliRunner

    monkeypatch.chdir(tmp_repo)
    _mock_make_http(monkeypatch)
    docs = _clean_docs(fixture_docs, tmp_repo / "docs-copy")
    result = CliRunner().invoke(app, ["freshen", "--dry-run", "--docs", str(docs)])
    assert result.exit_code == 0, result.output
    assert "m1/01-harness" in result.output and "minor" in result.output
    assert not (tmp_repo / "freshness").exists()


def _freshen_env(tmp_git_repo, fixture_docs, monkeypatch, replies):
    from miubais import cli
    from miubais.model import FakeModelClient

    monkeypatch.chdir(tmp_git_repo)
    _mock_make_http(monkeypatch)
    client = FakeModelClient(replies)
    monkeypatch.setattr(cli, "default_client", lambda: client)
    return _clean_docs(fixture_docs, tmp_git_repo / "docs-copy"), client


def test_freshen_commits_report_and_drafts_on_branch(tmp_git_repo, fixture_docs, monkeypatch):
    import subprocess
    from datetime import UTC, datetime

    from miubais.cli import app
    from miubais.model import ModelResult
    from typer.testing import CliRunner

    note = ModelResult(text="check section 2", structured=None, cost_usd=0.0, session_id=None)
    docs, client = _freshen_env(tmp_git_repo, fixture_docs, monkeypatch, [note] * 10)
    result = CliRunner().invoke(app, ["freshen", "--docs", str(docs)])
    assert result.exit_code == 0, result.output
    branch = f"freshen/{datetime.now(UTC).date().isoformat()}"
    assert f"branch {branch} at " in result.output
    files = subprocess.check_output(
        ["git", "-C", str(tmp_git_repo), "ls-tree", "-r", "--name-only", branch], text=True
    )
    assert "freshness/latest.json" in files and "freshness/drafts/" in files
    assert f", {len(client.requests)} drafts" in result.output and client.requests
    assert "freshness/latest.json" in files
    assert (
        subprocess.check_output(
            ["git", "-C", str(tmp_git_repo), "status", "--porcelain", "--untracked-files=no"],
            text=True,
        )
        == ""
    )
    assert not (tmp_git_repo / "freshness" / "latest.json").exists()


def test_freshen_no_drafts_skips_model(tmp_git_repo, fixture_docs, monkeypatch):
    from miubais.cli import app
    from typer.testing import CliRunner

    docs, client = _freshen_env(tmp_git_repo, fixture_docs, monkeypatch, [])
    result = CliRunner().invoke(app, ["freshen", "--no-drafts", "--docs", str(docs)])
    assert result.exit_code == 0, result.output
    assert "0 drafts" in result.output and client.requests == []


def test_freshen_refuses_dirty_tracked_files(tmp_git_repo, fixture_docs, monkeypatch):
    from miubais.cli import app
    from typer.testing import CliRunner

    docs, _ = _freshen_env(tmp_git_repo, fixture_docs, monkeypatch, [])
    (tmp_git_repo / "freshness" / ".keep").write_text("dirty")
    result = CliRunner().invoke(app, ["freshen", "--no-drafts", "--docs", str(docs)])
    assert result.exit_code == 1 and "freshness/.keep" in result.output
    assert not (tmp_git_repo / "freshness" / "latest.json").exists()


def test_freshen_explicit_out_skips_git(tmp_git_repo, fixture_docs, monkeypatch):
    import subprocess

    from miubais.cli import app
    from typer.testing import CliRunner

    docs, _ = _freshen_env(tmp_git_repo, fixture_docs, monkeypatch, [])
    out = tmp_git_repo / "elsewhere"
    result = CliRunner().invoke(
        app, ["freshen", "--no-drafts", "--docs", str(docs), "--out", str(out)]
    )
    assert result.exit_code == 0 and "skipping git branch" in result.output
    lessons = json.loads((out / "latest.json").read_text())["lessons"]
    assert lessons and all(row["path"].startswith("docs-copy/") for row in lessons)
    assert (
        subprocess.check_output(["git", "-C", str(tmp_git_repo), "branch", "--list", "freshen/*"])
        == b""
    )


def test_freshen_reports_bad_frontmatter(tmp_repo, fixture_docs, monkeypatch):
    from miubais.cli import app
    from typer.testing import CliRunner

    monkeypatch.chdir(tmp_repo)
    result = CliRunner().invoke(app, ["freshen", "--dry-run", "--docs", str(fixture_docs)])
    assert result.exit_code == 1 and "bad-" in result.output
