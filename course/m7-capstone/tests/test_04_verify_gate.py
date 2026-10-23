import os
import tempfile

import pytest
from capstone import verify
from capstone.types import PR


@pytest.fixture
def pr(repo):
    return lambda pr_id: PR.load(repo / "prs" / pr_id)


@pytest.fixture
def scratch(tmp_path, monkeypatch):
    root = tmp_path / "tmp"
    root.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(root))
    return root


def test_apply_patch_copies_the_fixture_without_prs_and_applies(repo, pr, tmp_path):
    applied = verify.apply_patch(repo, pr("pr-01").patch, tmp_path / "tree")
    assert applied.ok and applied.conflicts == []
    assert applied.tree == tmp_path / "tree"
    assert not (applied.tree / "prs").exists()
    assert (applied.tree / ".claude" / "rules" / "web.md").is_file()
    assert "formatDue" in (applied.tree / "web" / "src" / "format.ts").read_text()
    assert "formatDue" not in (repo / "web" / "src" / "format.ts").read_text()


def test_only_the_top_level_prs_folder_is_left_out(tmp_path):
    repo = tmp_path / "repo"
    (repo / "prs" / "pr-01").mkdir(parents=True)
    (repo / "internal" / "prs").mkdir(parents=True)
    (repo / "internal" / "prs" / "prs.go").write_text("package prs\n")
    patch = repo / "prs" / "pr-01" / "patch.diff"
    patch.write_text(
        "diff --git a/a.txt b/a.txt\nnew file mode 100644\n--- /dev/null\n+++ b/a.txt\n"
        "@@ -0,0 +1 @@\n+a\n"
    )
    applied = verify.apply_patch(repo, patch, tmp_path / "tree")
    tree = applied.tree
    assert applied.ok and (tree / "a.txt").is_file()
    assert not (tree / "prs").exists()
    assert (tree / "internal" / "prs" / "prs.go").is_file()


def test_a_conflicting_patch_names_the_file_and_leaves_the_copy_untouched(repo, pr, tmp_path):
    applied = verify.apply_patch(repo, pr("pr-10").patch, tmp_path / "tree")
    assert not applied.ok
    assert applied.conflicts == ["internal/api/errors.go"]
    for name in ("internal/api/errors.go", "internal/api/handlers.go", "CHANGELOG.json"):
        assert (applied.tree / name).read_text() == (repo / name).read_text(), name


def test_pr_01_passes_both_sides(repo, pr, scratch):
    applied, result = verify.gate(repo, pr("pr-01"))
    assert applied.ok
    assert (result.go_ok, result.ts_ok) == (True, True), result.output
    assert not result.failed
    assert result.duration_ms > 0


def test_pr_07_fails_the_typescript_tests(repo, pr, scratch):
    applied, result = verify.gate(repo, pr("pr-07"))
    assert applied.ok
    assert (result.go_ok, result.ts_ok) == (True, False), result.output


def test_pr_09_fails_the_go_tests(repo, pr, scratch):
    applied, result = verify.gate(repo, pr("pr-09"))
    assert applied.ok
    assert (result.go_ok, result.ts_ok) == (False, True), result.output
    assert "FAIL" in result.output


def test_a_conflict_yields_no_verify_run(repo, pr, scratch, monkeypatch):
    def must_not_run(*args, **kwargs):
        raise AssertionError("verify ran on a tree the patch did not apply to")

    monkeypatch.setattr(verify, "run", must_not_run)
    applied, result = verify.gate(repo, pr("pr-10"))
    assert not applied.ok
    assert applied.conflicts == ["internal/api/errors.go"]
    assert result is None


def test_gate_removes_its_temporary_tree(repo, pr, scratch):
    applied, _ = verify.gate(repo, pr("pr-10"))
    assert not applied.tree.exists()
    assert list(scratch.iterdir()) == []


def test_gate_keeps_the_tree_when_given_a_destination(repo, pr, tmp_path, scratch):
    applied, result = verify.gate(repo, pr("pr-01"), tmp_path / "tree")
    assert applied.ok and result is not None and not result.failed
    assert applied.tree == tmp_path / "tree"
    assert "formatDue" in (applied.tree / "web" / "src" / "format.ts").read_text()
    assert list(scratch.iterdir()) == []


def test_a_missing_tool_is_none_not_a_failure(repo, tmp_path, monkeypatch):
    tree = tmp_path / "tree"
    tree.mkdir()
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    result = verify.run(tree)
    assert (result.go_ok, result.ts_ok) == (None, None)
    assert not result.failed


def test_a_hanging_command_times_out_as_a_failure(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("go", "exec /bin/sleep 30"), ("node", "exit 0")):
        script = bin_dir / name
        script.write_text(f"#!/bin/sh\n{body}\n")
        script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}/usr/bin{os.pathsep}/bin")
    tree = tmp_path / "tree"
    tree.mkdir()
    result = verify.run(tree, timeout=1)
    assert (result.go_ok, result.ts_ok) == (False, True)
    assert 1000 <= result.duration_ms < 10_000
