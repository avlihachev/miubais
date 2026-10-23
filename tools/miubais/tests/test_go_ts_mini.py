import json
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import frontmatter
import pytest
import yaml
from miubais.paths import course_dir, repo_root

FIXTURE = repo_root() / "fixtures" / "go-ts-mini"
LABELS_PATH = course_dir() / "m7-capstone" / "tests" / "LABELS.yaml"
PR_IDS = [f"pr-{n:02d}" for n in range(1, 13)]
CONFLICTING = "pr-10"
CLEAN = {"pr-01", "pr-11"}
CATEGORIES = {
    "proto-field-reuse",
    "proto-missing-reserved",
    "migration-number-collision",
    "migration-edited-applied",
    "changelog-missing",
    "input-unvalidated",
    "ts-any",
    "test-removed",
    "secret-in-code",
    "error-swallowed",
    "api-breaking",
    "style",
}
BLOCKER_KINDS = {
    "stale-migration",
    "missing-second-approval",
    "conflict",
    "unreviewed-age",
    "verify-failed",
}
HARD_BLOCKERS = {"conflict", "stale-migration", "verify-failed"}
SCOPED_RULES = {"proto.md", "migrations.md", "api.md", "web.md"}


def tool(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        pytest.fail(f"needs {name}: install it to check the go-ts-mini fixture")
    return path


def labels() -> dict:
    return yaml.safe_load(LABELS_PATH.read_text())


def base_copy(dest: Path) -> Path:
    shutil.copytree(FIXTURE, dest, ignore=shutil.ignore_patterns("prs"))
    return dest


def patch_path(pr: str) -> Path:
    return FIXTURE / "prs" / pr / "patch.diff"


def git_apply(root: Path, pr: str, *flags: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [tool("git"), "apply", *flags, str(patch_path(pr))],
        check=False,
        cwd=root,
        capture_output=True,
        text=True,
    )


def run(root: Path, *cmd: str) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=False, cwd=root, capture_output=True, text=True, timeout=300)


def touched_files(pr: str) -> set[str]:
    text = patch_path(pr).read_text()
    return set(re.findall(r"^\+\+\+ b/(\S+)", text, re.MULTILINE)) | set(
        re.findall(r"^--- a/(\S+)", text, re.MULTILINE)
    )


@pytest.fixture(scope="module")
def patched(tmp_path_factory) -> dict[str, Path]:
    trees = {}
    for pr in PR_IDS:
        if pr == CONFLICTING:
            continue
        root = base_copy(tmp_path_factory.mktemp(pr) / "repo")
        result = git_apply(root, pr)
        assert result.returncode == 0, f"{pr}: {result.stderr}"
        trees[pr] = root
    return trees


def test_go_tests_pass_on_the_base(tmp_path):
    result = run(base_copy(tmp_path / "repo"), tool("go"), "test", "./...")
    assert result.returncode == 0, result.stdout + result.stderr


def test_node_tests_pass_on_the_base(tmp_path):
    result = run(base_copy(tmp_path / "repo"), tool("node"), "--test")
    assert result.returncode == 0, result.stdout + result.stderr
    assert re.search(r"^ℹ pass ([1-9]\d*)$", result.stdout, re.MULTILINE), result.stdout


@pytest.mark.parametrize("pr", [p for p in PR_IDS if p != CONFLICTING])
def test_patch_applies_to_the_base(pr, tmp_path):
    result = git_apply(base_copy(tmp_path / "repo"), pr, "--check")
    assert result.returncode == 0, result.stderr


def test_conflicting_patch_does_not_apply(tmp_path):
    result = git_apply(base_copy(tmp_path / "repo"), CONFLICTING, "--check")
    assert result.returncode != 0
    assert "does not apply" in result.stderr


@pytest.mark.parametrize("pr", PR_IDS)
def test_pr_directory_shape(pr):
    meta = json.loads((FIXTURE / "prs" / pr / "meta.json").read_text())
    assert set(meta) == {"title", "author", "created_at", "approvals", "description"}
    assert re.fullmatch(r"2026-\d\d-\d\d", meta["created_at"])
    assert meta["author"] not in meta["approvals"]
    text = patch_path(pr).read_text()
    assert 20 <= len(text.splitlines()) <= 120
    assert text.startswith("diff --git a/")


def verify(root: Path) -> str:
    go = run(root, tool("go"), "test", "./...")
    node = run(root, tool("node"), "--test")
    return "pass" if go.returncode == 0 and node.returncode == 0 else "fail"


@pytest.mark.slow
def test_verify_labels_match_the_patched_trees(patched):
    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = dict(zip(patched, pool.map(verify, patched.values()), strict=True))
    assert outcomes == {pr: labels()[pr]["verify"] for pr in patched}


def test_labels_cover_all_twelve_prs():
    assert sorted(labels()) == PR_IDS
    assert sorted(p.name for p in (FIXTURE / "prs").iterdir() if p.is_dir()) == PR_IDS


@pytest.mark.parametrize("pr", PR_IDS)
def test_label_values_are_from_the_enums(pr):
    label = labels()[pr]
    assert set(label) == {"findings", "blockers", "verify", "decision"}
    assert set(label["blockers"]) <= BLOCKER_KINDS
    assert label["verify"] in {"pass", "fail", "conflict"}
    for finding in label["findings"]:
        assert set(finding) == {"file", "start", "end", "category", "severity"}
        assert finding["category"] in CATEGORIES
        assert finding["severity"] in {"blocker", "major", "minor"}
        assert 1 <= finding["start"] <= finding["end"]


@pytest.mark.parametrize("pr", PR_IDS)
def test_decision_follows_the_rule(pr):
    label = labels()[pr]
    blockers = set(label["blockers"])
    severe = any(f["severity"] == "blocker" for f in label["findings"])
    if severe or blockers & HARD_BLOCKERS:
        expected = "block"
    elif blockers or any(f["severity"] == "major" for f in label["findings"]):
        expected = "hold"
    else:
        expected = "merge"
    assert label["decision"] == expected
    assert ("verify-failed" in blockers) == (label["verify"] == "fail")
    assert ("conflict" in blockers) == (label["verify"] == "conflict") == (pr == CONFLICTING)


@pytest.mark.parametrize("pr", [p for p in PR_IDS if p != CONFLICTING])
def test_labelled_lines_lie_in_touched_files(pr, patched):
    for finding in labels()[pr]["findings"]:
        assert finding["file"] in touched_files(pr), finding
        lines = (patched[pr] / finding["file"]).read_text().splitlines()
        assert finding["end"] <= len(lines), finding


def test_clean_prs_have_no_findings():
    for pr in CLEAN:
        assert labels()[pr]["findings"] == []
    assert labels()["pr-01"]["decision"] == "merge"
    assert labels()["pr-01"]["blockers"] == []
    assert labels()["pr-11"]["decision"] == "hold"


def meta(pr: str) -> dict:
    return json.loads((FIXTURE / "prs" / pr / "meta.json").read_text())


def new_migrations(pr: str) -> list[int]:
    text = patch_path(pr).read_text()
    added = re.findall(r"^--- /dev/null\n\+\+\+ b/migrations/(\d{4})_", text, re.MULTILINE)
    return [int(number) for number in added]


def test_planted_approval_age_and_migration_cases():
    as_of = date(2026, 10, 17)
    existing = [int(p.name[:4]) for p in (FIXTURE / "migrations").glob("*.sql")]
    contract = {
        pr
        for pr in PR_IDS
        if any(f.startswith(("proto/", "migrations/")) for f in touched_files(pr))
    }
    for pr in contract:
        assert len(meta(pr)["approvals"]) == (1 if pr == "pr-03" else 2), pr
    second = {pr for pr in contract if len(meta(pr)["approvals"]) < 2}
    aged = {
        pr
        for pr in PR_IDS
        if not meta(pr)["approvals"]
        and as_of - date.fromisoformat(meta(pr)["created_at"]) > timedelta(days=14)
    }
    stale = {
        pr
        for pr in PR_IDS
        if any(n != max(existing) + 1 or n in existing for n in new_migrations(pr))
    }
    assert (second, aged, stale) == ({"pr-03"}, {"pr-11"}, {"pr-04"})
    for kind, expected in [
        ("missing-second-approval", second),
        ("unreviewed-age", aged),
        ("stale-migration", stale),
    ]:
        assert {pr for pr in PR_IDS if kind in labels()[pr]["blockers"]} == expected, kind


def test_rules_frontmatter_parses():
    rules = {p.name: frontmatter.load(p) for p in (FIXTURE / ".claude" / "rules").glob("*.md")}
    assert set(rules) == SCOPED_RULES | {"changelog.md"}
    for name in SCOPED_RULES:
        paths = rules[name].metadata["paths"]
        assert paths and isinstance(paths, (list, str)), name
        assert rules[name].content.strip()
    assert "paths" not in rules["changelog.md"].metadata


def test_manifest_lists_every_pr_without_naming_planted_issues():
    manifest = (FIXTURE / "MANIFEST.md").read_text()
    assert "provenance: original" in manifest and "as_of: 2026-10-17" in manifest
    for pr in PR_IDS:
        title = json.loads((FIXTURE / "prs" / pr / "meta.json").read_text())["title"]
        assert f"| {pr} | {title} |" in manifest
    lowered = manifest.lower()
    assert not [word for word in CATEGORIES | BLOCKER_KINDS if word in lowered]


def test_fixture_is_mit_licensed():
    assert (FIXTURE / "LICENSE").read_text().startswith("MIT License")
    assert "go 1.27" in (FIXTURE / "go.mod").read_text()
