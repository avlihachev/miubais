import asyncio
from pathlib import Path

import pytest
from harness_lab.hooks import guard_hook
from harness_lab.policy import Guard
from harness_lab.types import Verdict


def call(hook, event):
    return asyncio.run(hook(event, "toolu_1", {"signal": None}))


@pytest.fixture
def root(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    return tmp_path / "src"


@pytest.fixture
def guard(root: Path) -> Guard:
    return Guard([root], [r"rm\s+-rf"])


def test_allow_is_empty_dict(guard, root, hook_event):
    event = hook_event("Write", {"file_path": str(root / "a.py")}, cwd=str(root))
    assert call(guard_hook(guard), event) == {}


def test_deny_has_exact_sdk_shape(guard, root, tmp_path, hook_event):
    event = hook_event("Write", {"file_path": str(tmp_path / "x.py")}, cwd=str(root))
    out = call(guard_hook(guard), event)
    assert set(out) == {"hookSpecificOutput"}
    specific = out["hookSpecificOutput"]
    assert set(specific) == {"hookEventName", "permissionDecision", "permissionDecisionReason"}
    assert specific["hookEventName"] == "PreToolUse"
    assert specific["permissionDecision"] == "deny"
    assert specific["permissionDecisionReason"]


def test_deny_echoes_event_name(guard, root, hook_event):
    event = hook_event("Bash", {"command": "rm -rf /"}, event="PreToolUse", cwd=str(root))
    out = call(guard_hook(guard), event)
    assert out["hookSpecificOutput"]["hookEventName"] == event["hook_event_name"]


@pytest.mark.parametrize("event_name", ["PermissionRequest", "PostToolUse"])
def test_other_events_get_no_decision(guard, root, hook_event, event_name):
    event = hook_event("Bash", {"command": "rm -rf /"}, event=event_name, cwd=str(root))
    assert call(guard_hook(guard), event) == {}


def test_guard_that_raises_denies_with_exception_text(root, hook_event):
    class Broken:
        def check(self, tool, args, cwd):
            raise RuntimeError("policy table unreadable")

    out = call(guard_hook(Broken()), hook_event("Write", {"file_path": "a.py"}, cwd=str(root)))
    specific = out["hookSpecificOutput"]
    assert specific["permissionDecision"] == "deny"
    assert "policy table unreadable" in specific["permissionDecisionReason"]


def test_guard_receives_tool_args_and_cwd(root, hook_event):
    seen = []

    class Spy:
        def check(self, tool, args, cwd):
            seen.append((tool, args, cwd))
            return Verdict(True, "ok")

    call(guard_hook(Spy()), hook_event("Bash", {"command": "ls"}, cwd=str(root)))
    assert seen == [("Bash", {"command": "ls"}, root)]


def test_rewrite_maps_write_into_root_with_updated_input(guard, root, hook_event):
    hook = guard_hook(guard, rewrite={"/tmp/x": str(root / "x")})
    out = call(hook, hook_event("Write", {"file_path": "/tmp/x", "content": "hi"}, cwd=str(root)))
    assert out == {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "updatedInput": {"file_path": str(root / "x"), "content": "hi"},
        }
    }


def test_rewrite_target_is_still_checked(guard, root, tmp_path, hook_event):
    hook = guard_hook(guard, rewrite={"/tmp/x": str(tmp_path / "elsewhere")})
    out = call(hook, hook_event("Write", {"file_path": "/tmp/x", "content": "hi"}, cwd=str(root)))
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_unmapped_path_is_not_rewritten(guard, root, hook_event):
    hook = guard_hook(guard, rewrite={"/tmp/x": str(root / "x")})
    event = hook_event("Write", {"file_path": str(root / "a.py")}, cwd=str(root))
    assert call(hook, event) == {}
