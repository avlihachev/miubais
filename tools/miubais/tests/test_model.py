import asyncio
from pathlib import Path

import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock
from miubais.model import (
    DISALLOWED_TOOLS,
    AgentSdkClient,
    FakeModelClient,
    ModelError,
    ModelRequest,
    ModelResult,
    path_guard,
)


def test_fake_client_records_requests_and_replays():
    c = FakeModelClient([ModelResult(text="hi", structured=None, cost_usd=0.0, session_id=None)])
    r = asyncio.run(
        c.complete(ModelRequest(system="s", prompt="p", cwd=Path("."), allowed_tools=[]))
    )
    assert r.text == "hi" and c.requests[0].prompt == "p"


def _req(**kw):
    return ModelRequest(system="s", prompt="p", cwd=Path("."), allowed_tools=["Read"], **kw)


def test_fake_client_raises_exception_entries():
    c = FakeModelClient([RuntimeError("boom")])
    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(c.complete(_req()))
    assert len(c.requests) == 1


def test_fake_client_exhaustion_is_clear():
    with pytest.raises(AssertionError, match="no responses left"):
        asyncio.run(FakeModelClient([]).complete(_req()))


def _result(subtype="success", is_error=False, structured=None, cost=0.25, errors=None):
    return ResultMessage(
        subtype=subtype,
        duration_ms=1,
        duration_api_ms=1,
        is_error=is_error,
        num_turns=1,
        session_id="sid",
        total_cost_usd=cost,
        structured_output=structured,
        errors=errors,
    )


def _assistant(*texts):
    return AssistantMessage(content=[TextBlock(text=t) for t in texts], model="m")


def _patch_query(monkeypatch, messages):
    seen = {}

    async def fake_query(*, prompt, options):
        seen["prompt"] = prompt
        seen["options"] = options
        for m in messages:
            yield m

    monkeypatch.setattr("claude_agent_sdk.query", fake_query)
    return seen


def test_sdk_client_passes_options_and_collects_result(monkeypatch):
    seen = _patch_query(
        monkeypatch,
        [_assistant("one", "two"), _assistant("three"), _result(structured={"a": 1})],
    )
    schema = {"type": "object"}
    r = asyncio.run(AgentSdkClient(model="m1").complete(_req(max_turns=2, schema=schema)))
    assert r == ModelResult(
        text="one\ntwo\nthree", structured={"a": 1}, cost_usd=0.25, session_id="sid", model="m"
    )
    o = seen["options"]
    assert seen["prompt"] == "p"
    assert o.disallowed_tools == DISALLOWED_TOOLS
    assert o.allowed_tools == ["Read"]
    assert o.permission_mode == "dontAsk"
    assert o.setting_sources == []
    assert o.max_turns == 2
    assert o.model == "m1"
    assert o.output_format == {"type": "json_schema", "schema": schema}


def test_sdk_client_request_model_overrides_and_no_schema(monkeypatch):
    seen = _patch_query(monkeypatch, [_assistant("x"), _result()])
    asyncio.run(AgentSdkClient(model="m1").complete(_req(model="m2")))
    assert seen["options"].model == "m2"
    assert seen["options"].output_format is None


def test_sdk_client_error_subtype_raises_with_cost(monkeypatch):
    _patch_query(
        monkeypatch,
        [_assistant("partial"), _result(subtype="error_max_turns", is_error=True)],
    )
    with pytest.raises(ModelError) as e:
        asyncio.run(AgentSdkClient().complete(_req()))
    assert (e.value.subtype, e.value.cost_usd, e.value.session_id) == (
        "error_max_turns",
        0.25,
        "sid",
    )


def test_sdk_client_missing_result_raises(monkeypatch):
    _patch_query(monkeypatch, [_assistant("x")])
    with pytest.raises(ModelError, match="without a result"):
        asyncio.run(AgentSdkClient().complete(_req()))


def test_sdk_client_missing_structured_output_raises(monkeypatch):
    _patch_query(monkeypatch, [_assistant("x"), _result()])
    with pytest.raises(ModelError, match="structured"):
        asyncio.run(AgentSdkClient().complete(_req(schema={"type": "object"})))


def test_sdk_client_allow_web_lifts_only_web_tools(monkeypatch):
    seen = _patch_query(monkeypatch, [_assistant("x"), _result()])
    asyncio.run(AgentSdkClient(model="m1").complete(_req(allow_web=True)))
    disallowed = seen["options"].disallowed_tools
    assert "WebFetch" not in disallowed and "WebSearch" not in disallowed
    assert {"Write", "Edit", "Bash", "Agent"} <= set(disallowed)


def _event(tool, **tool_input):
    return {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input}


def _decide(guard, event):
    out = asyncio.run(guard(event, "t1", None))
    return out.get("hookSpecificOutput", {}).get("permissionDecision", "allow")


@pytest.fixture
def guarded(tmp_path):
    ws = tmp_path / "workspace" / "x"
    (ws / "src").mkdir(parents=True)
    readme = tmp_path / "course" / "x" / "README.md"
    readme.parent.mkdir(parents=True)
    readme.write_text("r")
    (tmp_path / "course" / "x" / "reference").mkdir()
    denied: list[str] = []
    return ws, readme, path_guard([ws, readme], ws, denied), denied


def test_path_guard_allows_workspace_and_readme(guarded):
    ws, readme, guard, denied = guarded
    assert _decide(guard, _event("Read", file_path=str(ws / "src" / "a.py"))) == "allow"
    assert _decide(guard, _event("Read", file_path="src/a.py")) == "allow"
    assert _decide(guard, _event("Read", file_path=str(readme))) == "allow"
    assert _decide(guard, _event("Grep", pattern="def add")) == "allow"
    assert _decide(guard, _event("Glob", pattern="**/*.py", path=str(ws))) == "allow"
    assert denied == []


def test_path_guard_denies_reference_and_escapes(guarded):
    _ws, readme, guard, denied = guarded
    reference = readme.parent / "reference" / "a.py"
    assert _decide(guard, _event("Read", file_path=str(reference))) == "deny"
    assert _decide(guard, _event("Read", file_path="../../course/x/reference/a.py")) == "deny"
    assert _decide(guard, _event("Grep", pattern="add", path=str(readme.parent))) == "deny"
    assert _decide(guard, _event("Glob", pattern="../../course/**/*.py")) == "deny"
    assert (
        _decide(guard, _event("Glob", pattern=str(readme.parent / "reference" / "*.py"))) == "deny"
    )
    assert _decide(guard, _event("Grep", pattern="add", glob="../../course/**")) == "deny"
    assert len(denied) == 6


def test_path_guard_deny_shape(guarded):
    _ws, _readme, guard, _ = guarded
    out = asyncio.run(guard(_event("Read", file_path="/etc/hosts"), "t1", None))
    spec = out["hookSpecificOutput"]
    assert spec["hookEventName"] == "PreToolUse" and spec["permissionDecision"] == "deny"
    assert "/etc/hosts" in spec["permissionDecisionReason"]


def test_sdk_client_installs_path_hook_when_scoped(monkeypatch, tmp_path):
    seen = _patch_query(monkeypatch, [_assistant("x"), _result()])
    asyncio.run(AgentSdkClient().complete(_req(allowed_paths=[tmp_path])))
    matchers = seen["options"].hooks["PreToolUse"]
    assert matchers[0].matcher == "Read|Grep|Glob" and len(matchers[0].hooks) == 1


def test_sdk_client_no_hook_when_unscoped(monkeypatch):
    seen = _patch_query(monkeypatch, [_assistant("x"), _result()])
    asyncio.run(AgentSdkClient().complete(_req()))
    assert not seen["options"].hooks


def test_sdk_client_wraps_sdk_exceptions(monkeypatch):
    from claude_agent_sdk import CLINotFoundError

    async def broken(*, prompt, options):
        raise CLINotFoundError("claude not found")
        yield

    monkeypatch.setattr("claude_agent_sdk.query", broken)
    with pytest.raises(ModelError, match="claude not found"):
        asyncio.run(AgentSdkClient().complete(_req()))


def test_sdk_client_reports_model_from_messages(monkeypatch):
    _patch_query(monkeypatch, [_assistant("x"), _result()])
    r = asyncio.run(AgentSdkClient(model="m1").complete(_req()))
    assert r.model == "m"
