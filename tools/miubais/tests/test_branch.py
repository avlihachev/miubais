import subprocess
from datetime import date
from pathlib import Path

import pytest
from miubais.freshness.branch import BranchError, clean_for_freshen, commit_on_branch

DAY = date(2026, 10, 16)


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


@pytest.fixture
def report_files(tmp_git_repo):
    out = tmp_git_repo / "freshness"
    (out / "drafts").mkdir()
    files = [out / "latest.json", out / "report-2026-10-16.md", out / "drafts" / "m1__a.md"]
    for f in files:
        f.write_text(f.name)
    return [(f, f.relative_to(tmp_git_repo)) for f in files]


def test_clean_ignores_untracked_and_other_dirs(tmp_git_repo):
    (tmp_git_repo / "freshness" / "new.md").write_text("x")
    (tmp_git_repo / "other.txt").write_text("x")
    assert clean_for_freshen(tmp_git_repo) == []


def test_branch_refuses_dirty_site(tmp_git_repo):
    tracked = tmp_git_repo / "site/src/content/docs/x.md"
    tracked.write_text("one")
    git(tmp_git_repo, "add", "-A")
    git(tmp_git_repo, "commit", "-m", "x")
    tracked.write_text("edited")
    with pytest.raises(BranchError) as e:
        commit_on_branch(tmp_git_repo, DAY, [])
    assert "site/src/content/docs/x.md" in str(e.value)


def test_branch_commits_report_in_worktree(tmp_git_repo, report_files):
    sha = commit_on_branch(tmp_git_repo, DAY, report_files)
    assert git(tmp_git_repo, "rev-parse", "freshen/2026-10-16") == sha
    assert git(tmp_git_repo, "show", "--stat", "--format=%s", sha).startswith(
        "freshness: report 2026-10-16"
    )
    assert git(tmp_git_repo, "show", f"{sha}:freshness/drafts/m1__a.md") == "m1__a.md"
    assert git(tmp_git_repo, "status", "--porcelain", "--untracked-files=no") == ""
    assert git(tmp_git_repo, "branch", "--show-current") == "main"
    assert "miubais-freshen-" not in git(tmp_git_repo, "worktree", "list").split("\n", 1)[-1]


def test_branch_rerun_reuses_branch_and_is_idempotent(tmp_git_repo, report_files):
    first = commit_on_branch(tmp_git_repo, DAY, report_files)
    assert commit_on_branch(tmp_git_repo, DAY, report_files) == first


def test_failed_copy_deletes_new_branch(tmp_git_repo):
    missing = tmp_git_repo / "nope.txt"
    with pytest.raises(BranchError):
        commit_on_branch(tmp_git_repo, DAY, [(missing, Path("freshness/nope.txt"))])
    assert git(tmp_git_repo, "branch", "--list", "freshen/*") == ""
    assert git(tmp_git_repo, "worktree", "list").count("\n") == 0


def test_failed_rerun_keeps_existing_branch(tmp_git_repo, report_files):
    commit_on_branch(tmp_git_repo, DAY, report_files)
    with pytest.raises(BranchError):
        commit_on_branch(tmp_git_repo, DAY, [(tmp_git_repo / "nope", Path("freshness/n"))])
    assert git(tmp_git_repo, "branch", "--list", "freshen/2026-10-16")
