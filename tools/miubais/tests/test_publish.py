import subprocess

import pytest
from miubais.cli import app
from miubais.publish import (
    BUILTIN_CONTENT_PATTERNS,
    check_export,
    export_tree,
    load_denylist,
    overlay_paths,
    scan_content,
    select_public,
)
from typer.testing import CliRunner

PUBLIC = [
    "course/m0-cost-lab/tests/KEY.yaml",
    "course/m0-cost-lab/tests/.leak-terms",
    "tools/miubais/tests/fixtures/course/x-sample/reference/src/sample_lab/__init__.py",
    "site/src/pages/map.astro",
    "freshness/latest.json",
]
PRIVATE = [
    "course/m0-cost-lab/reference/src/a.py",
    "book/build.sh",
    "docs/video/x.md",
    "research/00.md",
    "site/src/pages/book.astro",
    "README.md",
    "publish/README.md",
    "freshness/report-2026-10-16.md",
]


def test_private_patterns_drop_reference_but_keep_keys_and_fixture_reference():
    assert select_public(PUBLIC + PRIVATE) == sorted(PUBLIC)


def test_tutor_eval_cases_and_runs_are_private_but_the_tutor_is_public():
    evals = "tools/miubais/src/miubais/tutor/evals"
    tracked = [
        f"{evals}/cases/m0-01-tool-loop.yaml",
        f"{evals}/cases/README.md",
        f"{evals}/runs/latest.jsonl",
        "tools/miubais/src/miubais/tutor/evals.py",
        "tools/miubais/src/miubais/tutor/policy.md",
    ]
    assert select_public(tracked) == [
        "tools/miubais/src/miubais/tutor/evals.py",
        "tools/miubais/src/miubais/tutor/policy.md",
    ]


def test_overlay_maps_publish_dir_to_root():
    assert overlay_paths(["publish/README.md", "publish/.github/workflows/ci.yml", "site/x"]) == {
        "publish/README.md": "README.md",
        "publish/.github/workflows/ci.yml": ".github/workflows/ci.yml",
    }


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    for rel in PUBLIC + PRIVATE:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(f"content of {rel}")
    (root / "publish/README.md").write_text("public readme")
    (root / "README.md").write_text("private readme")
    return root


def snapshot(dest):
    return sorted(
        (p.relative_to(dest).as_posix(), p.read_bytes())
        for p in dest.rglob("*")
        if p.is_file() and p.relative_to(dest).parts[0] != ".git"
    )


def test_export_tree_copies_overlays_and_removes_stale(repo, tmp_path):
    dest = tmp_path / "dest"
    (dest / ".git").mkdir(parents=True)
    (dest / ".git/HEAD").write_text("ref: refs/heads/main\n")
    (dest / "stale.txt").write_text("old")
    (dest / "site/src/pages").mkdir(parents=True)
    (dest / "site/src/pages/map.astro").write_text("old map")
    report = export_tree(repo, dest, PUBLIC + PRIVATE)
    assert (dest / "README.md").read_text() == "public readme"
    assert (dest / "site/src/pages/map.astro").read_text() == "content of site/src/pages/map.astro"
    assert not (dest / "course/m0-cost-lab/reference").exists()
    assert not (dest / "publish").exists() and not (dest / "book").exists()
    assert (dest / ".git/HEAD").exists() and not (dest / "stale.txt").exists()
    assert report.removed == ["stale.txt"]
    assert report.copied == sorted([*PUBLIC, "README.md"])


def test_export_is_deterministic(repo, tmp_path):
    export_tree(repo, tmp_path / "a", PUBLIC + PRIVATE)
    export_tree(repo, tmp_path / "b", PUBLIC + PRIVATE)
    assert snapshot(tmp_path / "a") == snapshot(tmp_path / "b")


def test_check_export_flags_private_file_and_missing_leak_terms(tmp_path):
    dest = tmp_path / "dest"
    (dest / "course/x/tests").mkdir(parents=True)
    (dest / "course/x/reference").mkdir()
    (dest / "course/x/stages.yaml").write_text("exercise: x\n")
    (dest / "course/x/reference/a.py").write_text("x = 1\n")
    assert check_export(dest) == ["course/x/reference/a.py", "course/x/tests/.leak-terms"]


def test_check_export_accepts_overlay_readme_and_git_dir(tmp_path):
    dest = tmp_path / "dest"
    (dest / ".git").mkdir(parents=True)
    (dest / ".git/publish-manifest").write_text("README.md\n")
    (dest / "README.md").write_text("public readme")
    assert check_export(dest) == []


def test_check_export_rejects_unknown_top_level(tmp_path):
    dest = tmp_path / "dest"
    (dest / "notes").mkdir(parents=True)
    (dest / "notes/a.md").write_text("x")
    assert "notes" in check_export(dest)


@pytest.fixture
def published_repo(tmp_git_repo, monkeypatch):
    files = {
        "course/x/stages.yaml": "exercise: x\n",
        "course/x/starter/a.py": "x = 1\n",
        "course/x/tests/.leak-terms": "secret_name\n",
        "course/x/reference/a.py": "secret_name = 1\n",
        "book/a.md": "private\n",
        "README.md": "private readme\n",
        "publish/README.md": "public readme\n",
    }
    for rel, text in files.items():
        (tmp_git_repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_git_repo / rel).write_text(text)
    git(tmp_git_repo, "add", "-A")
    git(tmp_git_repo, "commit", "-m", "course")
    monkeypatch.chdir(tmp_git_repo)
    return tmp_git_repo


def git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def dest(tmp_path_factory):
    return tmp_path_factory.mktemp("public") / "dest"


def test_publish_cli_refuses_dirty_tree(published_repo, dest):
    (published_repo / "freshness/.keep").write_text("changed")
    res = CliRunner().invoke(app, ["publish", "--dest", str(dest)])
    assert res.exit_code == 1 and "working tree is dirty" in res.output
    assert not dest.exists()


def test_publish_cli_dry_run_writes_nothing(published_repo, dest):
    res = CliRunner().invoke(app, ["publish", "--dest", str(dest), "--dry-run"])
    assert res.exit_code == 0, res.output
    assert "course: 3" in res.output and "book" not in res.output
    assert not dest.exists()


def test_publish_cli_exports_and_writes_manifest(published_repo, dest):
    res = CliRunner().invoke(app, ["publish", "--dest", str(dest)])
    assert res.exit_code == 0, res.output
    assert "copied 7 files, removed 0" in res.output
    assert (dest / ".git/publish-manifest").read_text().splitlines() == [
        "README.md",
        "course/x/stages.yaml",
        "course/x/starter/a.py",
        "course/x/tests/.leak-terms",
        "freshness/.keep",
        "pyproject.toml",
        "site/src/content/docs/.keep",
    ]
    assert (dest / "README.md").read_text() == "public readme\n"


def test_publish_cli_fails_on_missing_leak_terms(published_repo, dest):
    assert CliRunner().invoke(app, ["publish", "--dest", str(dest)]).exit_code == 0
    git(published_repo, "rm", "-q", "course/x/tests/.leak-terms")
    git(published_repo, "commit", "-m", "drop terms")
    res = CliRunner().invoke(app, ["publish", "--dest", str(dest)])
    assert res.exit_code == 1 and "course/x/tests/.leak-terms" in res.output
    assert not (dest / ".git/publish-manifest").exists()


def test_publish_cli_fails_on_content_hit(published_repo, dest):
    home = published_repo / "home"
    home.mkdir(exist_ok=True)
    (home / "publish-denylist.txt").write_text("zebra-corp\n")
    (published_repo / "course/x/starter/a.py").write_text("x = 1\n# made for Zebra-Corp\n")
    git(published_repo, "commit", "-qam", "client name")
    res = CliRunner().invoke(app, ["publish", "--dest", str(dest), "--dry-run"])
    assert res.exit_code == 1 and "course/x/starter/a.py:2: deny:1" in res.output
    assert not dest.exists()
    res = CliRunner().invoke(app, ["publish", "--dest", str(dest)])
    assert res.exit_code == 1 and "course/x/starter/a.py:2: deny:1" in res.output
    assert not (dest / ".git/publish-manifest").exists()


def test_publish_cli_warns_without_denylist(published_repo, dest):
    res = CliRunner().invoke(app, ["publish", "--dest", str(dest), "--dry-run"])
    assert res.exit_code == 0, res.output
    assert "no denylist at" in res.output
    assert "content scan: 7 files, 0 hits, denylist none" in res.output


def test_publish_cli_dry_run_reports_offenders(published_repo, dest):
    git(published_repo, "rm", "-q", "course/x/tests/.leak-terms")
    (published_repo / "notes").mkdir()
    (published_repo / "notes/a.md").write_text("x\n")
    git(published_repo, "add", "notes/a.md")
    git(published_repo, "commit", "-m", "drop terms, add notes")
    res = CliRunner().invoke(app, ["publish", "--dest", str(dest), "--dry-run"])
    assert res.exit_code == 1
    assert "course/x/tests/.leak-terms" in res.output and "  notes" in res.output
    assert not dest.exists()


@pytest.mark.parametrize("target", [".", "out", ".."])
def test_publish_cli_refuses_dest_overlapping_repo(published_repo, target):
    (published_repo / "untracked.md").write_text("work in progress\n")
    res = CliRunner().invoke(app, ["publish", "--dest", target])
    assert res.exit_code == 1 and "overlaps the repository" in res.output
    assert (published_repo / "untracked.md").read_text() == "work in progress\n"
    assert (published_repo / "book/a.md").is_file() and not (published_repo / "out").exists()


def test_publish_cli_refuses_non_empty_dest_that_is_not_a_clone(published_repo, dest):
    dest.mkdir()
    (dest / "notes.md").write_text("keep me\n")
    res = CliRunner().invoke(app, ["publish", "--dest", str(dest)])
    assert res.exit_code == 1
    assert f"refusing to export into {dest.resolve()}: it is not empty and not a git clone" in (
        res.output
    )
    assert (dest / "notes.md").read_text() == "keep me\n"


def test_publish_cli_counts_only_files_tracked_in_the_clone(published_repo, dest):
    dest.mkdir()
    git(dest, "init", "-q", "-b", "main")
    (dest / "old.md").write_text("old\n")
    git(dest, "add", "old.md")
    for i in range(30):
        (dest / f"node_modules/pkg{i}.js").parent.mkdir(exist_ok=True)
        (dest / f"node_modules/pkg{i}.js").write_text("x\n")
    res = CliRunner().invoke(app, ["publish", "--dest", str(dest), "--dry-run"])
    assert res.exit_code == 0, res.output
    assert "would remove 1\n  old.md" in res.output and "node_modules" not in res.output
    res = CliRunner().invoke(app, ["publish", "--dest", str(dest)])
    assert res.exit_code == 0 and "copied 7 files, removed 1" in res.output


def test_publish_cli_dry_run_prints_only_the_count_of_many_removals(published_repo, dest):
    dest.mkdir()
    git(dest, "init", "-q", "-b", "main")
    for i in range(21):
        (dest / f"old{i}.md").write_text("old\n")
    git(dest, "add", ".")
    res = CliRunner().invoke(app, ["publish", "--dest", str(dest), "--dry-run"])
    assert res.exit_code == 0, res.output
    assert "would remove 21" in res.output and "old0.md" not in res.output


def write_tree(root, files):
    for rel, data in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, bytes):
            (root / rel).write_bytes(data)
        else:
            (root / rel).write_text(data)
    return list(files)


def test_scan_content_flags_cyrillic_and_home_path(tmp_path):
    paths = write_tree(
        tmp_path,
        {
            "site/a.md": "intro\nnote: \u0434\u043e\u043c\u0430\n",
            "tools/b.py": "x = 1\nroot = '/Us" + "ers/alice/proj'\n",
            "fixtures/c.txt": "dev home /home/dev/app and /Users/x/repo\n",
        },
    )
    assert scan_content(tmp_path, paths, BUILTIN_CONTENT_PATTERNS) == [
        "site/a.md:2: cyrillic",
        "tools/b.py:2: home-path",
    ]


def test_scan_content_skips_binary_and_locks(tmp_path):
    cyrillic = "\u0434\u043e\u043c\u0430\n"
    paths = write_tree(
        tmp_path,
        {
            "site/logo.png": b"\x89PNG\x00" + cyrillic.encode(),
            "site/pnpm-lock.yaml": cyrillic,
            "uv.lock": cyrillic,
            "site/b.md": cyrillic,
        },
    )
    assert scan_content(tmp_path, paths, BUILTIN_CONTENT_PATTERNS) == ["site/b.md:1: cyrillic"]


KNOWN_FAKES = (
    '"anthropic-key": "sk-ant-api03-Zx9fakeFAKEfake0123456789",',
    '"github-token": "ghp_FAKEfakeFAKEfake0123456789abcd",',
    'monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-fake")',
    'monkeypatch.setenv("GITHUB_TOKEN", "ghp_fake")',
    '"tool_response": {"stdout": "API_KEY=sk-ant-api03-fake", "interrupted": False},',
    'response = {"stdout": "GITHUB_TOKEN=ghp_x", "stderr": "", "interrupted": False}',
    'SECRET = "sk-ant-api03-" + "Q" * 24',
    'fake_key = "sk-ant-api03-" + "EXAMPLE" * 3',
    'json.dumps({"log": json.dumps({"GITHUB_TOKEN": "ghp_" + "0" * 36})}),',
    'blob = base64.b64encode(b"key sk-ant-api03-EXAMPLEEXAMPLE").decode()',
    'parent = {"PATH": "/usr/bin", "HOME": "/home/dev", "CI": "1"}',
    '("anthropic-key", re.compile(r"sk-ant-[A-Za-z0-9_-]{8,}")),',
    '("github-token", re.compile(r"\\bghp_[A-Za-z0-9]{20,}")),',
)


def test_scan_content_ignores_known_fakes(tmp_path):
    fakes = "\n".join(KNOWN_FAKES)
    real = (
        "key = " + "sk-ant-" + "api03-k7Hq2LmN9pRt" + "\ntoken = " + "gh" + "p_" + "a1B2c3D4e5F6g7"
    )
    paths = write_tree(tmp_path, {"course/fakes.py": fakes + "\n", "course/real.py": real})
    assert scan_content(tmp_path, paths, BUILTIN_CONTENT_PATTERNS) == [
        "course/real.py:1: anthropic-key",
        "course/real.py:2: github-token",
    ]


def test_denylist_terms_are_applied(tmp_path):
    denylist = tmp_path / "publish-denylist.txt"
    denylist.write_text("# neutral test terms\nzebra-corp\n\n\\bokapi\\b\n")
    patterns = load_denylist(denylist)
    assert [name for name, _ in patterns] == ["deny:2", "deny:4"]
    paths = write_tree(
        tmp_path / "tree",
        {"site/a.md": "built at Zebra-Corp\nokapis are fine\nan OKAPI is not\n"},
    )
    assert scan_content(tmp_path / "tree", paths, patterns) == [
        "site/a.md:1: deny:2",
        "site/a.md:3: deny:4",
    ]
    assert load_denylist(tmp_path / "missing.txt") == []
