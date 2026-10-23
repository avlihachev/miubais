from pathlib import Path

import pytest
from harness_lab.policy import Guard


@pytest.fixture
def root(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    return tmp_path / "src"


BLOCKED = [
    r"\brm\s+(?:[^\s;&|]+\s+)*?(?:-[a-z]*r[a-z]*|--recursive)\b",
    r"\bgit(?:\s+(?:-c\s+\S+|--(?:git-dir|work-tree|namespace)\s+\S+|--?[\w-]+(?:=\S+)?))*\s+push\b",
    r"\bsudo\b",
]


@pytest.fixture
def guard(root: Path) -> Guard:
    return Guard([root], BLOCKED)


@pytest.mark.parametrize("tool", ["Write", "Edit", "MultiEdit", "NotebookEdit"])
def test_write_inside_root_is_allowed(guard, root, tool):
    assert guard.check(tool, {"file_path": str(root / "a.py")}, root).ok


def test_relative_write_resolves_against_cwd(guard, root):
    assert guard.check("Write", {"file_path": "pkg/a.py"}, root).ok


def test_write_outside_root_is_denied_with_reason(guard, root, tmp_path):
    verdict = guard.check("Write", {"file_path": str(tmp_path / "other.py")}, root)
    assert not verdict.ok
    assert verdict.why


def test_dotdot_traversal_is_denied(guard, root):
    assert not guard.check("Edit", {"file_path": str(root / ".." / "escape.py")}, root).ok
    assert not guard.check("Edit", {"file_path": "../escape.py"}, root).ok


def test_symlink_out_of_root_is_denied(guard, root, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "link").symlink_to(outside)
    assert not guard.check("Write", {"file_path": str(root / "link" / "a.py")}, root).ok


def test_write_without_path_is_denied(guard, root):
    assert not guard.check("Write", {}, root).ok


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf build",
        "rm -r -f build",
        "rm -Rf build",
        "rm --recursive --force build",
        "git push origin main",
        "git -C ../other push",
        "git --git-dir x push",
        "git --work-tree x push",
        "sudo ls",
    ],
)
def test_blocked_commands_are_denied(guard, root, command):
    assert not guard.check("Bash", {"command": command}, root).ok


@pytest.mark.parametrize(
    "command",
    [
        "rm -f stale.pyc",
        "rm -f a && grep -r foo .",
        "rm -f a; grep -r foo .",
        "git log --grep push",
        "git -C . status",
    ],
)
def test_near_misses_are_allowed(guard, root, command):
    assert guard.check("Bash", {"command": command}, root).ok


def test_blocked_patterns_ignore_case(root):
    guard = Guard([root], [r"git\s+push", r"rm\s+-rf"])
    assert not guard.check("Bash", {"command": "GIT PUSH origin main"}, root).ok
    assert not guard.check("Bash", {"command": "RM -RF build"}, root).ok


def test_plain_command_is_allowed(guard, root):
    assert guard.check("Bash", {"command": "pytest -q"}, root).ok


def test_redirect_outside_roots_is_denied(guard, root, tmp_path):
    outside = tmp_path / "x.txt"
    assert not guard.check("Bash", {"command": f"echo hi > {outside}"}, root).ok
    assert not guard.check("Bash", {"command": f"echo hi >> {outside}"}, root).ok


def test_redirect_inside_roots_is_allowed(guard, root):
    assert guard.check("Bash", {"command": f"echo hi > {root / 'x.txt'}"}, root).ok
    assert guard.check("Bash", {"command": "echo hi >> out.txt"}, root).ok


def test_quoted_redirect_target_is_checked(guard, root):
    assert not guard.check("Bash", {"command": 'echo x > "/etc/passwd"'}, root).ok
    assert not guard.check("Bash", {"command": "echo x > '/etc/passwd'"}, root).ok


@pytest.mark.parametrize(
    "command", ["pytest -q 2>&1", "pytest -q > /dev/null", "pytest 2>&1 > /dev/null"]
)
def test_fd_duplication_and_dev_null_are_allowed(guard, root, command):
    assert guard.check("Bash", {"command": command}, root).ok


@pytest.mark.parametrize("tool", ["Read", "Grep", "Glob"])
def test_read_tools_are_allowed(guard, root, tool):
    assert guard.check(tool, {"path": "/etc/hosts"}, root).ok


def test_unknown_tool_is_denied(guard, root):
    verdict = guard.check("WebFetch", {"url": "https://example.com"}, root)
    assert not verdict.ok
    assert "WebFetch" in verdict.why
