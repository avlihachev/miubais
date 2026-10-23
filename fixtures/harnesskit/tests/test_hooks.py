import asyncio
from pathlib import Path

import pytest
from harnesskit.hooks import allow, deny, post_tool_use, pre_tool_use
from harnesskit.policy import Decision, Policy


def event(tool_name: str, tool_input: dict, cwd: Path, name: str = "PreToolUse") -> dict:
    return {
        "hook_event_name": name,
        "session_id": "s1",
        "transcript_path": "/tmp/t.jsonl",
        "cwd": str(cwd),
        "tool_name": tool_name,
        "tool_input": tool_input,
    }


def call(hook, input_data: dict) -> dict:
    return asyncio.run(hook(input_data, "toolu_1", {"signal": None}))


@pytest.fixture
def policy(tmp_path: Path) -> Policy:
    return Policy(writable=[tmp_path / "src"])


def test_allow_is_empty():
    assert allow() == {}


def test_deny_shape():
    assert deny("PreToolUse", "nope") == {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": "nope",
        }
    }


def test_hook_allows(policy, tmp_path):
    assert call(pre_tool_use(policy), event("Read", {"file_path": "x"}, tmp_path)) == {}


def test_hook_denies_with_exact_shape(policy, tmp_path):
    out = call(pre_tool_use(policy), event("Write", {"file_path": "x.py"}, tmp_path))
    assert set(out) == {"hookSpecificOutput"}
    spec = out["hookSpecificOutput"]
    assert spec["hookEventName"] == "PreToolUse"
    assert spec["permissionDecision"] == "deny"
    assert "writable" in spec["permissionDecisionReason"]


def test_hook_echoes_event_name(policy, tmp_path):
    out = call(pre_tool_use(policy), event("Nope", {}, tmp_path))
    assert out["hookSpecificOutput"]["hookEventName"] == "PreToolUse"


@pytest.mark.parametrize("name", ["PermissionRequest", "PostToolUse"])
def test_other_events_get_no_decision(policy, tmp_path, name):
    out = call(pre_tool_use(policy), event("Bash", {"command": "sudo ls"}, tmp_path, name=name))
    assert out == {}


def test_hook_resolves_relative_paths_against_event_cwd(policy, tmp_path):
    (tmp_path / "src").mkdir()
    out = call(pre_tool_use(policy), event("Write", {"file_path": "src/a.py"}, tmp_path))
    assert out == {}


class Exploding(Policy):
    def decide(self, tool_name, tool_input, cwd, *, agent_type=None):
        raise RuntimeError("boom in policy")


class PerAgent(Policy):
    def decide(self, tool_name, tool_input, cwd, *, agent_type=None):
        if agent_type == "reviewer" and tool_name != "Read":
            return Decision(False, "the reviewer only reads")
        return super().decide(tool_name, tool_input, cwd, agent_type=agent_type)


def test_hook_passes_agent_type_to_the_policy(tmp_path):
    hook = pre_tool_use(PerAgent(writable=[tmp_path]))
    write = event("Write", {"file_path": "a.py"}, tmp_path)
    assert call(hook, write) == {}
    out = call(hook, write | {"agent_type": "reviewer", "agent_id": "a1"})
    assert out["hookSpecificOutput"]["permissionDecisionReason"] == "the reviewer only reads"


def test_hook_denies_when_policy_raises(tmp_path):
    hook = pre_tool_use(Exploding(writable=[tmp_path]))
    out = call(hook, event("Read", {"file_path": "x"}, tmp_path))
    spec = out["hookSpecificOutput"]
    assert spec["permissionDecision"] == "deny"
    assert "boom in policy" in spec["permissionDecisionReason"]


def test_hook_denies_on_malformed_input(policy):
    out = call(pre_tool_use(policy), {"hook_event_name": "PreToolUse"})
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_audit_sees_every_decision(policy, tmp_path):
    seen: list[dict] = []
    hook = pre_tool_use(policy, audit=seen.append)
    call(hook, event("Read", {"file_path": "x"}, tmp_path))
    call(hook, event("Bash", {"command": "sudo ls"}, tmp_path))
    assert [(e["tool_name"], e["allow"]) for e in seen] == [("Read", True), ("Bash", False)]
    assert seen[1]["tool_use_id"] == "toolu_1" and "denied" in seen[1]["reason"]


def test_failing_audit_never_allows(policy, tmp_path):
    def audit(entry):
        raise OSError("disk full")

    out = call(pre_tool_use(policy, audit=audit), event("Read", {"file_path": "x"}, tmp_path))
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def post_event(response, name: str = "PostToolUse") -> dict:
    return {
        "hook_event_name": name,
        "tool_name": "Bash",
        "tool_input": {"command": "ls"},
        "tool_response": response,
        "tool_use_id": "toolu_1",
    }


def test_post_tool_use_wraps_replacement():
    hook = post_tool_use(lambda data: data["tool_response"].upper())
    assert call(hook, post_event("out")) == {
        "hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedToolOutput": "OUT"}
    }


def test_post_tool_use_passthrough_on_none():
    assert call(post_tool_use(lambda data: None), post_event("out")) == {}


def test_post_tool_use_ignores_other_events():
    seen = []
    hook = post_tool_use(lambda data: seen.append(data))
    assert call(hook, post_event("out", name="PreToolUse")) == {}
    assert seen == []


def test_post_tool_use_raising_transform_keeps_result():
    errors = []

    def boom(data):
        raise ValueError("bad")

    assert call(post_tool_use(boom, on_error=errors.append), post_event("out")) == {}
    assert len(errors) == 1 and isinstance(errors[0], ValueError)
    assert call(post_tool_use(boom), post_event("out")) == {}
